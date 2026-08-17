import httpx

from scraper.platforms.zepto.dashboard_data.seller import endpoints as ep
from app.utils.logger import logger

# TEMPORARY snapshot, captured live from Brik Oven's own account (2026-08-17) —
# NOT a general solution. The real API requires cityIds ("At least one City id
# is required") and appears to want the full subcategory set too; a production
# scraper needs these fetched dynamically per-tenant from Zepto's own
# city-list / brand-category-mapping endpoints, not frozen here. This exists
# only to prove the pre-flight-check + real-fetch chain works end to end.
_BRIK_OVEN_BRAND_ID = "b9cea5fc-da5f-4045-9b67-c07831733746"
_BRIK_OVEN_BRAND_NAME = "Brik Oven"
# API requires subcategoryNames count to match subcategoryIds count exactly.
_BRIK_OVEN_SUBCATEGORY_NAMES = "Breads & Buns|Cheese|Paneer & Cream"
_BRIK_OVEN_SUBCATEGORY_IDS = (
    "30566884-bbd7-49fa-8c3f-43c90a571c9e,"
    "f594b28a-4775-48ac-8840-b9030229ff87,"
    "1806412f-190a-46b1-be42-4237a4146eb1"
)
_BRIK_OVEN_CITY_IDS = (
    "5a17386b-33fb-43d4-bf71-258277768fcc,f2904c34-8099-4dd3-920f-910eb5205ac7,"
    "14005d55-f7ab-405f-a81e-e03d32e63f23,98141024-d057-49da-a307-82d88308db5d,"
    "facade53-8330-4ebe-b07e-55319220a301,03aa95b0-065c-4996-8214-0b50cdfc1de0,"
    "35e672bd-8f0e-4e9d-9391-5b977c4b52ea,ea6e2d03-d75e-474a-90a7-4e79096b5b45,"
    "f0e24877-3ed8-4026-a999-69bf3909cc40,05ed345b-bc36-44bc-9ef6-e9d5055eba40,"
    "549e0201-32a3-4580-9ef0-e40219ea80fc,f31e8f17-5547-41d9-906e-082c8b3e5f3d,"
    "82647e5a-8a81-41f8-8ed7-859e023c448f,b04b3be4-0cc7-4423-aa7d-b9ea346e8b0c,"
    "961e5cec-25b5-4cf1-b3f5-3ea445d542ad,ac7cd4f0-8980-41ee-9931-cbbd3865907c,"
    "170d7ace-25e7-4ecf-a2f7-a79024b2c8a2,028c397f-589f-4fa1-acdf-cd207dcd77a1,"
    "58ad7919-8b34-4364-93f8-43a955911988,960153c2-f137-44b9-8650-136abe528a9b,"
    "9e3216dc-1aff-41c4-bae7-75058158e6d3,4dda0cbc-9e53-4e45-98f8-87f574857e12,"
    "30735969-391b-478c-a81c-be93115f87a8,c0a2f546-6da6-4edf-9fe8-7389bb6b12a9,"
    "1d3b9a09-ee94-48c3-a4dd-3401a751a22f,df57e573-88e7-4b72-a0bf-bae998ad1114,"
    "76c6e4cb-adab-48fd-aa48-bffd412b3c03,d4f93f80-56c6-44d3-af5c-c37e70e11770,"
    "b99507d6-d709-4939-876c-41dafbb98ec1,ed4f0a63-4887-4b08-b89c-bf1ac1703f54,"
    "67ba5a13-59ed-4e8f-b279-44a7978c516b,cfb80653-9139-4530-a8ed-4ab8c62f7cdf,"
    "014af366-5112-4363-9b52-6226a2ff48d9,c13eeeb7-d49a-4961-b6ba-93f14c9dd393,"
    "a64421ba-ce07-4688-bf9e-b97533ebda45,64153376-b4d5-495f-826f-89bd134f12f1,"
    "c5c88e82-be9a-4e49-9546-f269c0f714ec,e6db07ff-ae8d-4948-a2f7-5aa6a883d6b9,"
    "ce56c260-4cf6-4d10-b481-9ed2fd7a90d4,075236e1-be26-4084-a4fe-ceba0a69a5a0,"
    "ee671798-13f4-4127-a682-241a3e9b23db,29ec81c4-de2d-43c9-9585-a2eadbe4c7a0,"
    "79a5a1fe-a49f-419c-8599-a24a4c8abf9a,58b4b3e5-572d-491d-a9a3-66a5560e4291,"
    "9d4b400b-637c-4886-bf35-51231380ce61,71137ec6-dcd5-4ea2-be6a-56ec553b01d8,"
    "056e834d-a1d2-4df3-a93d-7ebd60e6bb16,d282106b-4b56-4205-a4fb-ffc562ef0232,"
    "3c91a871-2d4f-4d8a-a921-f2fb2859e0df,06f65018-add9-4340-b5f0-d33f43f626d3,"
    "7db839ab-3f17-42e7-bdc2-609caa492d53,8397d19b-5961-48ab-b1a0-c1ff6e7fcc72,"
    "8d9f53cd-ce19-45fe-947c-935ebf93ab7d,446ca947-2307-4175-87d3-2d0d792b2798,"
    "3ae99187-1625-4925-b490-6c1b080cd406,8db806ee-581c-46c0-a847-d9558957d97d,"
    "7c1962ea-0a21-47b3-bf6c-91afabddc237,f6d77ae4-f662-4f13-a0d5-dc75a72caddd,"
    "11b050ca-ab90-4f69-b70c-b3ad843ec16a,c68232c5-7375-43fe-a7ce-510d7530cbf6,"
    "f126bd15-c9b9-49a4-ad90-f4cd38af0148,a2b4beb2-7c4d-4749-bc95-5b04d4adf837,"
    "df73cdc7-5840-4f42-bb66-c84a6f52b9c4,fea7e548-473c-4cf9-bc1b-a6fd4d9bb0e2,"
    "6d68408e-e1f6-42aa-808b-a7ae899ff4f5,1c678705-4565-415b-bbf6-e89efc48fbed,"
    "5f7f16e5-7b3b-4c97-ab3a-011b5f24a642,15862867-2c01-4699-8cfe-2a2d19bee4f1,"
    "f0576bcd-df97-4a6f-bda7-36442c0046a8,078d5e32-627a-4907-8df8-4360bc7c06da,"
    "16f9be64-9fe0-4c07-b58c-f69b0d3d0610,47e68964-42b7-489c-a698-b5a6bdebd374,"
    "bb5bb05a-5c71-4038-b342-4f1aab72d9a6,d0c5c4c5-ab54-407d-a6f0-d924610c86a6,"
    "80d4c4c1-ddbe-4106-89d9-fcf71ad2d1c2,f7cf85b0-4de9-4f49-b58f-0b061c0235ff,"
    "3cd6c684-388d-45b4-b050-ac6cc2803028,3de94802-07a4-47c0-947e-65d61302752f,"
    "09edd4b5-baf6-44f5-8001-58f129d048f8,bd1a192b-521a-4c9f-a2e5-7166e6f76152,"
    "7e926d2f-adad-4e5a-956f-f07fffa54164,72fb38ea-adb8-468a-9d7b-be46ae9d7fc1,"
    "82c98de3-2610-47d9-ab70-251330bcb704,c5b3d670-f20e-4cae-a6b7-42e17b8fb08d,"
    "3eb31521-2060-4beb-b6fb-18ba88b6adda,81f24084-8358-4d11-8b79-1acd7efd6a91,"
    "a1dcbfe4-e614-4c2c-8143-c277d1aba5f8,a730455f-f1a8-4a3f-83f8-a427d82ffe0b,"
    "d04d97a9-c33f-4c19-8834-e6799104bcab,6142585c-ee69-4c59-8272-a26e7fc39f35,"
    "9123ec08-699e-4804-ad97-39d32254491b,c0ba5589-10d2-4367-985d-c4efc7bb978a,"
    "550e8400-e29b-41d4-a716-446655440021,951ec7c2-2eb9-420e-9918-81a9837da992,"
    "8e6bfeb7-25f2-41c2-be52-75fc98c8025c,f87237b7-cfda-4b7b-949e-a2198dc60a85,"
    "169ee922-31e9-4c90-9117-38234c705b84,e92d0690-1df3-474b-9a5a-14e9761dfae3,"
    "1f68f9e5-6d06-4feb-b2a1-4f208c648951,f938d139-3cb7-4b78-8980-b88178659225,"
    "6f4693d9-6c78-4cd5-8ccd-3d69ad5cc0ef,fdafe514-505f-4a0a-a7fb-c948ac90e3fb,"
    "c0d479f8-52bf-4781-8d56-ecfcb21b41d1,93c3fda1-9112-462b-99da-95b3b2ca52dd,"
    "bedfb594-54b5-4976-8b57-3e1f347e413a,1d0d217f-de88-42c3-b22d-57fdb9aacc94,"
    "575ac75c-83c5-47bd-8983-f63fb5e2e606,ffc28d34-ea44-400b-9821-4abb309c3e01,"
    "55871558-d0f9-4391-b539-3f435c894d7c,60faade0-708d-4c8a-a2c4-3a937bc38912,"
    "d37c8904-cf88-42df-b61c-e2980795911e,62df0ce0-f79c-4ab2-b87c-d5796f6e1519,"
    "d337388e-1a65-40b4-b89d-0d15c78d611f,2dab747c-3811-457e-964d-0c86fe1c7d64,"
    "388df8a5-218a-4e80-9138-897f70252a75,7bf1aea5-d147-4b29-b741-36fe0361b8b8,"
    "449216c9-1760-4194-a9d4-06f5b3ddb7db,1fe2c80a-4342-49ef-a80d-4a9002957312,"
    "ade1ab24-deac-4683-b903-05e879129073,224f9c13-a918-4c3b-88ff-aa1617648b69,"
    "ee66dc2a-aded-4445-a7b2-1ad63715725c,ddf073f6-808e-491a-9cd8-6f1763b38aaa,"
    "bd39f3ce-1d0f-45fc-8d91-a1ab70b69f90,963e4758-abc3-4766-a26c-bdc4d0c30bd2,"
    "df1ecb02-77a5-47b1-aa59-7c78ad69d1c5,8ed26cb7-eb7d-4b7b-8d8c-3e93d5855bdd,"
    "ae6b8c95-8015-42f6-b9dd-2f63171b25cd,11a03c2a-11cd-4284-9f91-128ed0d41ae2,"
    "e4a25eda-b544-439a-9239-6c698262ffc0,6b5ce365-da73-42a5-928e-57ab66890a6b,"
    "1e8f1393-93b6-4532-a5ba-92781dbc085f,b4fc5b4c-ef99-4d24-be15-f8690c35955b,"
    "f3cbc158-35a4-4c2c-ac5e-56e1fa5b08fd,3917931a-6d2e-4824-85dc-5871d3363b28,"
    "24ba2926-b0f0-4039-bf00-52a8f603d27e,4f30407c-6a3c-4a4e-8a3d-652217d4b6cb,"
    "a5f8dc56-616d-4123-b256-047249ff1176,967b5dc4-46b9-4d50-ae1e-6f2b58923e64"
)


def _extract_auth(storage_state: dict) -> tuple[str, str] | None:
    """Pull the JWT and WAF token straight out of the saved cookies — no
    browser needed. Confirmed live (DevTools + captured requests) that
    Zepto's frontend sends these cookie values verbatim as the `authorization`
    and `x-aws-waf-token` headers on every API call, so replaying them here
    is equivalent to what the real page does."""
    jwt = None
    waf_token = None
    for c in storage_state.get("cookies", []):
        name = c.get("name", "")
        if name.endswith("_AUTH_TOKEN"):
            jwt = c.get("value")
        elif name == "aws-waf-token":
            waf_token = c.get("value")
    if not jwt or not waf_token:
        return None
    return jwt, waf_token


async def validate(storage_state: dict) -> tuple[bool, str | None]:
    """Cheap, browser-free check: is this saved session still accepted by
    Zepto's API? Deliberately avoids launching a browser at all — a headless
    page load was observed (live) to trigger AWS WAF's bot-challenge flow,
    so routine health checks use a single plain HTTP request instead, which
    looks like any other API call rather than a fresh browser session."""
    auth = _extract_auth(storage_state)
    if not auth:
        return False, "Saved session is missing the auth or WAF-token cookie"
    jwt, waf_token = auth

    headers = {
        "authorization": jwt,
        "x-aws-waf-token": waf_token,
        "x-proxy-target": "brand-analytics",
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{ep.BASE_URL}{ep.USER_INFO_API}", headers=headers, timeout=15)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if resp.status_code == 200:
        logger.info("Zepto seller session validation: OK")
        return True, None

    error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    logger.warning(f"Zepto seller session validation failed: {error}")
    return False, error


async def fetch_sales_overview(storage_state: dict, date_from: str, date_to: str) -> dict:
    """Real GMV/Units data from Zepto's Sales Analytics — direct API call,
    no browser. Uses the temporary Brik-Oven-only ID snapshot above; a
    tenant-general version needs those fetched dynamically first."""
    auth = _extract_auth(storage_state)
    if not auth:
        raise RuntimeError("Saved session is missing the auth or WAF-token cookie")
    jwt, waf_token = auth

    headers = {
        "authorization": jwt,
        "x-aws-waf-token": waf_token,
        "x-proxy-target": "brand-analytics",
        "accept": "application/json",
    }
    params = {
        "brandIds": _BRIK_OVEN_BRAND_ID,
        "brandNames": _BRIK_OVEN_BRAND_NAME,
        "subcategoryNames": _BRIK_OVEN_SUBCATEGORY_NAMES,
        "subcategoryIds": _BRIK_OVEN_SUBCATEGORY_IDS,
        "cityIds": _BRIK_OVEN_CITY_IDS,
        "startDate": date_from,
        "endDate": date_to,
        "viewType": "BRAND",
        "aggregationLevel": "DAY",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ep.BASE_URL}{ep.SALES_OVERVIEW_API}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"]

    gmv = data["headers"]["gmv"]["value"]
    units = data["headers"]["units"]["value"]
    daily = data["metrics"]["gmv"]["data"]
    logger.info(f"Zepto sales-overview [{date_from}..{date_to}]: GMV={gmv} Units={units} ({len(daily)} days)")
    return data
