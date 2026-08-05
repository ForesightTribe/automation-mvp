BASE_URL = "https://partnersbiz.com"

# Login selectors used to live here. They are gone: logging in no longer drives a
# browser at all — see platform_auth/marketplaces/blinkit/seller.py, which uses
# the REST endpoints directly. The "account selection screen" those selectors
# clicked through turned out to be pure client state (localStorage myEntity),
# resolvable via GET /v1/get-user-entities/.
