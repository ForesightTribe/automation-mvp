"""Reproduce the Brand Portal's `x-signature` in pure Python.

The portal computes it in a WebAssembly module (`media_loader`, a Rust
hmac-0.12 build). Rather than reverse the HMAC key out of the binary, we RUN the
binary — wasmtime plus a hand-port of the wasm-bindgen JS glue it expects.

    message   = JSON.stringify(app_version + str(timestamp_ms) + request_id)
    signature = getMediaURL(message, request_id, session_id)

  * `timestamp_ms` is the value also sent as `x-timestamp`
  * `request_id` is the value also sent as `x-client-request-id` — NOT the
    `request_context.request_id` inside the body, which is a different uuid
  * `session_id` is the `session_id` claim of the bearer JWT

Verified 2026-09-22: 8/8 signatures captured live from the portal were
reproduced byte-exactly by this module.

The wasm reads nothing but its own arguments — no storage, no network, no
crypto API — so the browser and this port produce identical output, and signing
needs no browser. (Sending the signed request is a different matter; see
session.py.) The `verify_integrity` export and the `webdriver` string inside the
binary are an anti-automation tripwire that never fires here, because nothing is
driving a browser at signing time.

NOT thread-safe: one wasm Store with a shared linear memory backs each instance.
`get_signer()` hands back a process-wide singleton; call it from one task at a
time (the scrape is sequential, so this costs nothing).
"""
import json
import threading
import time
from typing import Any

import httpx
from wasmtime import Engine, Func, Instance, Module, Store

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep


def _fetch_wasm() -> bytes:
    """The cached signer, downloading it once if we do not have it."""
    if ep.SIGNER_CACHE.exists():
        return ep.SIGNER_CACHE.read_bytes()
    logger.info(f"Fetching the Instamart signer: {ep.SIGNER_WASM_URL}")
    r = httpx.get(ep.SIGNER_WASM_URL, timeout=60)
    if r.status_code != 200 or not r.content.startswith(b"\x00asm"):
        raise RuntimeError(
            f"Could not fetch the signer wasm ({r.status_code}, "
            f"{len(r.content)} B). Swiggy may have rebuilt the bundle — recover "
            f"the new URL from a logged-in page (the only .wasm under "
            f".../brand-portal-client/instamart/) and update "
            f"endpoints.SIGNER_WASM_URL."
        )
    ep.SIGNER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ep.SIGNER_CACHE.write_bytes(r.content)
    logger.debug(f"Signer cached at {ep.SIGNER_CACHE} ({len(r.content)} B)")
    return r.content


class Signer:
    """One instantiated copy of the portal's signing wasm."""

    # wasm-bindgen keeps JS values in a slab addressed by index; the wasm side
    # passes those indices around. 128.. are the constants it expects to find.
    _FIXED = 132

    def __init__(self, wasm: bytes) -> None:
        self._undef: tuple = ("undefined",)
        self._global: tuple = ("global",)
        self._perf: tuple = ("performance",)
        self._nav: tuple = ("navigator",)
        self._heap: list[Any] = [self._undef] * 128 + [self._undef, None, True, False]
        self._next = len(self._heap)

        engine = Engine()
        module = Module(engine, wasm)
        self._store = Store(engine)
        imports = [Func(self._store, i.type, self._impl(i.name)) for i in module.imports]
        self._inst = Instance(self._store, module, imports)
        self._ex = self._inst.exports(self._store)
        self._mem = self._ex["memory"]

    # -- wasm-bindgen value slab ---------------------------------------------
    def _get(self, i: int) -> Any:
        return self._heap[i]

    def _add(self, obj: Any) -> int:
        if self._next == len(self._heap):
            self._heap.append(len(self._heap) + 1)
        idx = self._next
        self._next = self._heap[idx]
        self._heap[idx] = obj
        return idx

    def _drop(self, i: int) -> None:
        if i < self._FIXED:
            return
        self._heap[i] = self._next
        self._next = i

    # -- memory helpers ------------------------------------------------------
    def _read(self, ptr: int, n: int) -> bytes:
        return bytes(self._mem.read(self._store, ptr, ptr + n))

    def _str(self, ptr: int, n: int) -> str:
        return self._read(ptr, n).decode("utf-8")

    def _write_str(self, s: str) -> tuple[int, int]:
        data = s.encode("utf-8")
        ptr = self._ex["__wbindgen_export_1"](self._store, len(data), 1)
        self._mem.write(self._store, data, ptr)
        return ptr, len(data)

    # -- the imports the binary asks for -------------------------------------
    # Matched by substring, not exact name: wasm-bindgen suffixes them with a
    # per-build hash, so the two binaries (host / data client) differ in name
    # while wanting the same seventeen functions.
    def _impl(self, name: str):
        table = [
            ("now", lambda a: float(time.time() * 1000)),
            ("object_clone_ref", lambda a: self._add(self._get(a))),
            ("_call_", lambda a, b: self._add(self._global)),
            ("newnoargs", lambda a, b: self._add(self._global)),
            ("is_undefined", lambda a: 1 if self._get(a) is self._undef else 0),
            ("object_drop_ref", lambda a: self._drop(a)),
            ("boolean_get", self._boolean_get),
            ("_get_", lambda a, b: self._add(self._undef)),      # Reflect.get
            ("string_new", lambda a, b: self._add(self._str(a, b))),
            ("performance", lambda a: self._add(self._perf)),
            ("instanceof_Window", lambda a: 0),
            ("throw", self._throw),
            ("accessor_SELF", lambda: self._add(self._global)),
            ("accessor_WINDOW", lambda: self._add(self._global)),
            ("GLOBAL_THIS", lambda: self._add(self._global)),
            ("accessor_GLOBAL", lambda: self._add(self._global)),
            ("navigator", lambda a: self._add(self._nav)),
        ]
        for needle, fn in table:
            if needle in name:
                return fn
        raise KeyError(f"the signer wants an import we do not provide: {name}")

    def _boolean_get(self, a: int) -> int:
        v = self._get(a)
        return (1 if v else 0) if isinstance(v, bool) else 2

    def _throw(self, ptr: int, n: int):
        raise RuntimeError(f"signer wasm threw: {self._str(ptr, n)}")

    # -- the one call we care about ------------------------------------------
    def get_media_url(self, message: str, request_id: str, session_id: str) -> str:
        ret = self._ex["__wbindgen_add_to_stack_pointer"](self._store, -16)
        mp, ml = self._write_str(message)
        rp, rl = self._write_str(request_id)
        sp, sl = self._write_str(session_id)
        self._ex["getMediaURL"](self._store, ret, mp, ml, rp, rl, sp, sl)
        out_ptr = int.from_bytes(self._read(ret, 4), "little", signed=True)
        out_len = int.from_bytes(self._read(ret + 4, 4), "little", signed=True)
        out = self._str(out_ptr, out_len)
        self._ex["__wbindgen_export_3"](self._store, out_ptr, out_len, 1)
        self._ex["__wbindgen_add_to_stack_pointer"](self._store, 16)
        return out

    def sign(self, timestamp_ms: int, request_id: str, session_id: str,
             app_version: str = ep.APP_VERSION) -> str:
        """The `x-signature` for a call carrying this timestamp and request id."""
        message = json.dumps(app_version + str(timestamp_ms) + request_id)
        return self.get_media_url(message, request_id, session_id)


_signer: Signer | None = None
_lock = threading.Lock()


def get_signer() -> Signer:
    """The process-wide signer, instantiated (and the wasm fetched) on first use."""
    global _signer
    with _lock:
        if _signer is None:
            _signer = Signer(_fetch_wasm())
    return _signer
