"""Test helper: run a test with Zepto keyword-bid automations switched ON.

They are OFF in the product for now (2026-09-29, `marketplaces.keyword_bidding_refusal`),
but the bidding code is kept and still tested — these tests exercise it on purpose.
"""
import functools

from campaign_manager import config


def zepto_bidding_on(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        saved = config.ZEPTO_KEYWORD_BIDDING
        config.ZEPTO_KEYWORD_BIDDING = True
        try:
            return fn(*args, **kwargs)
        finally:
            config.ZEPTO_KEYWORD_BIDDING = saved
    return run
