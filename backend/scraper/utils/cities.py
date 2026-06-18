"""
City and per-platform zone definitions for all Indian cities where
Blinkit, Zepto, and Swiggy Instamart operate.

Each platform has its own zone list per city because dark-store locations
differ across platforms — the same neighbourhood may be served by stores
at different lat/lon coordinates depending on the app.

Zones marked # TODO are placeholders copied from the shared baseline.
Replace them with verified dark-store coordinates once your team has the data.

Platform availability (as of June 2026):
  B = Blinkit  Z = Zepto  I = Instamart
"""

from typing import TypedDict


class Zone(TypedDict):
    zone: str
    pincode: str
    lat: float
    lon: float


class PlatformConfig(TypedDict):
    zones: list[Zone]


class City(TypedDict):
    name: str
    state: str
    lat: float   # city centroid — display/fallback only
    lon: float
    pincode: str  # city default pincode — fallback only
    platforms: dict[str, PlatformConfig]


CITIES: dict[str, City] = {

    # ── Tier 1 — all three platforms ──────────────────────────────────────────

    "bengaluru": {
        "name": "Bengaluru", "state": "Karnataka",
        "lat": 12.9716, "lon": 77.5946, "pincode": "560001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Shivajinagar",  "pincode": "560001", "lat": 12.9767, "lon": 77.5713},
                {"zone": "Indiranagar",             "pincode": "560038", "lat": 12.9784, "lon": 77.6408},
                {"zone": "Koramangala 5th Block",   "pincode": "560095", "lat": 12.9279, "lon": 77.6271},
                {"zone": "HSR Layout Sector 1",     "pincode": "560102", "lat": 12.9116, "lon": 77.6474},
                {"zone": "Whitefield / EPIP",       "pincode": "560066", "lat": 12.9698, "lon": 77.7499},
                {"zone": "Electronic City Phase 1", "pincode": "560100", "lat": 12.8399, "lon": 77.6770},
                {"zone": "Jayanagar 4th T Block",   "pincode": "560041", "lat": 12.9250, "lon": 77.5938},
                {"zone": "Malleswaram",             "pincode": "560003", "lat": 13.0035, "lon": 77.5700},
                {"zone": "Yelahanka",               "pincode": "560064", "lat": 13.1007, "lon": 77.5963},
                {"zone": "BTM Layout 2nd Stage",    "pincode": "560076", "lat": 12.9165, "lon": 77.6101},
                {"zone": "Marathahalli",            "pincode": "560037", "lat": 12.9591, "lon": 77.6974},
                {"zone": "JP Nagar",                "pincode": "560078", "lat": 12.9003, "lon": 77.5850},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Shivajinagar",  "pincode": "560001", "lat": 12.9767, "lon": 77.5713},
                {"zone": "Indiranagar",             "pincode": "560038", "lat": 12.9784, "lon": 77.6408},
                {"zone": "Koramangala 5th Block",   "pincode": "560095", "lat": 12.9279, "lon": 77.6271},
                {"zone": "HSR Layout Sector 1",     "pincode": "560102", "lat": 12.9116, "lon": 77.6474},
                {"zone": "Whitefield / EPIP",       "pincode": "560066", "lat": 12.9698, "lon": 77.7499},
                {"zone": "Electronic City Phase 1", "pincode": "560100", "lat": 12.8399, "lon": 77.6770},
                {"zone": "Jayanagar 4th T Block",   "pincode": "560041", "lat": 12.9250, "lon": 77.5938},
                {"zone": "Malleswaram",             "pincode": "560003", "lat": 13.0035, "lon": 77.5700},
                {"zone": "Yelahanka",               "pincode": "560064", "lat": 13.1007, "lon": 77.5963},
                {"zone": "BTM Layout 2nd Stage",    "pincode": "560076", "lat": 12.9165, "lon": 77.6101},
                {"zone": "Marathahalli",            "pincode": "560037", "lat": 12.9591, "lon": 77.6974},
                {"zone": "JP Nagar",                "pincode": "560078", "lat": 12.9003, "lon": 77.5850},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Shivajinagar",  "pincode": "560001", "lat": 12.9767, "lon": 77.5713},
                {"zone": "Indiranagar",             "pincode": "560038", "lat": 12.9784, "lon": 77.6408},
                {"zone": "Koramangala 5th Block",   "pincode": "560095", "lat": 12.9279, "lon": 77.6271},
                {"zone": "HSR Layout Sector 1",     "pincode": "560102", "lat": 12.9116, "lon": 77.6474},
                {"zone": "Whitefield / EPIP",       "pincode": "560066", "lat": 12.9698, "lon": 77.7499},
                {"zone": "Electronic City Phase 1", "pincode": "560100", "lat": 12.8399, "lon": 77.6770},
                {"zone": "Jayanagar 4th T Block",   "pincode": "560041", "lat": 12.9250, "lon": 77.5938},
                {"zone": "Malleswaram",             "pincode": "560003", "lat": 13.0035, "lon": 77.5700},
                {"zone": "Yelahanka",               "pincode": "560064", "lat": 13.1007, "lon": 77.5963},
                {"zone": "BTM Layout 2nd Stage",    "pincode": "560076", "lat": 12.9165, "lon": 77.6101},
                {"zone": "Marathahalli",            "pincode": "560037", "lat": 12.9591, "lon": 77.6974},
                {"zone": "JP Nagar",                "pincode": "560078", "lat": 12.9003, "lon": 77.5850},
            ]},
        },
    },

    "mumbai": {
        "name": "Mumbai", "state": "Maharashtra",
        "lat": 19.0760, "lon": 72.8777, "pincode": "400001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "South Mumbai / Colaba", "pincode": "400001", "lat": 18.9220, "lon": 72.8347},
                {"zone": "Worli",                 "pincode": "400018", "lat": 19.0177, "lon": 72.8152},
                {"zone": "Bandra West",           "pincode": "400050", "lat": 19.0596, "lon": 72.8295},
                {"zone": "Andheri West",          "pincode": "400058", "lat": 19.1136, "lon": 72.8464},
                {"zone": "Andheri East / MIDC",   "pincode": "400069", "lat": 19.1176, "lon": 72.8742},
                {"zone": "Powai / Hiranandani",   "pincode": "400076", "lat": 19.1176, "lon": 72.9060},
                {"zone": "Malad West",            "pincode": "400064", "lat": 19.1870, "lon": 72.8480},
                {"zone": "Borivali West",         "pincode": "400092", "lat": 19.2307, "lon": 72.8567},
                {"zone": "Navi Mumbai / Vashi",   "pincode": "400703", "lat": 19.0765, "lon": 73.0146},
                {"zone": "Thane West",            "pincode": "400601", "lat": 19.2183, "lon": 72.9781},
                {"zone": "Kurla",                 "pincode": "400070", "lat": 19.0728, "lon": 72.8826},
                {"zone": "Dadar",                 "pincode": "400014", "lat": 19.0178, "lon": 72.8478},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "South Mumbai / Colaba", "pincode": "400001", "lat": 18.9220, "lon": 72.8347},
                {"zone": "Worli",                 "pincode": "400018", "lat": 19.0177, "lon": 72.8152},
                {"zone": "Bandra West",           "pincode": "400050", "lat": 19.0596, "lon": 72.8295},
                {"zone": "Andheri West",          "pincode": "400058", "lat": 19.1136, "lon": 72.8464},
                {"zone": "Andheri East / MIDC",   "pincode": "400069", "lat": 19.1176, "lon": 72.8742},
                {"zone": "Powai / Hiranandani",   "pincode": "400076", "lat": 19.1176, "lon": 72.9060},
                {"zone": "Malad West",            "pincode": "400064", "lat": 19.1870, "lon": 72.8480},
                {"zone": "Borivali West",         "pincode": "400092", "lat": 19.2307, "lon": 72.8567},
                {"zone": "Navi Mumbai / Vashi",   "pincode": "400703", "lat": 19.0765, "lon": 73.0146},
                {"zone": "Thane West",            "pincode": "400601", "lat": 19.2183, "lon": 72.9781},
                {"zone": "Kurla",                 "pincode": "400070", "lat": 19.0728, "lon": 72.8826},
                {"zone": "Dadar",                 "pincode": "400014", "lat": 19.0178, "lon": 72.8478},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "South Mumbai / Colaba", "pincode": "400001", "lat": 18.9220, "lon": 72.8347},
                {"zone": "Worli",                 "pincode": "400018", "lat": 19.0177, "lon": 72.8152},
                {"zone": "Bandra West",           "pincode": "400050", "lat": 19.0596, "lon": 72.8295},
                {"zone": "Andheri West",          "pincode": "400058", "lat": 19.1136, "lon": 72.8464},
                {"zone": "Andheri East / MIDC",   "pincode": "400069", "lat": 19.1176, "lon": 72.8742},
                {"zone": "Powai / Hiranandani",   "pincode": "400076", "lat": 19.1176, "lon": 72.9060},
                {"zone": "Malad West",            "pincode": "400064", "lat": 19.1870, "lon": 72.8480},
                {"zone": "Borivali West",         "pincode": "400092", "lat": 19.2307, "lon": 72.8567},
                {"zone": "Navi Mumbai / Vashi",   "pincode": "400703", "lat": 19.0765, "lon": 73.0146},
                {"zone": "Thane West",            "pincode": "400601", "lat": 19.2183, "lon": 72.9781},
                {"zone": "Kurla",                 "pincode": "400070", "lat": 19.0728, "lon": 72.8826},
                {"zone": "Dadar",                 "pincode": "400014", "lat": 19.0178, "lon": 72.8478},
            ]},
        },
    },

    "delhi": {
        "name": "Delhi", "state": "Delhi",
        "lat": 28.6139, "lon": 77.2090, "pincode": "110001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Connaught Place / Central", "pincode": "110001", "lat": 28.6280, "lon": 77.2190},
                {"zone": "South Delhi / Saket",       "pincode": "110017", "lat": 28.5244, "lon": 77.2066},
                {"zone": "Greater Kailash 1",         "pincode": "110048", "lat": 28.5494, "lon": 77.2501},
                {"zone": "Rohini Sector 3",           "pincode": "110085", "lat": 28.7041, "lon": 77.1025},
                {"zone": "Dwarka Sector 12",          "pincode": "110078", "lat": 28.5900, "lon": 77.0460},
                {"zone": "Lajpat Nagar",              "pincode": "110024", "lat": 28.5700, "lon": 77.2430},
                {"zone": "Preet Vihar / East Delhi",  "pincode": "110092", "lat": 28.6346, "lon": 77.2948},
                {"zone": "Noida Sector 18",           "pincode": "201301", "lat": 28.5706, "lon": 77.3211},
                {"zone": "Noida Sector 62",           "pincode": "201309", "lat": 28.6248, "lon": 77.3638},
                {"zone": "Gurgaon DLF Phase 2",       "pincode": "122002", "lat": 28.4807, "lon": 77.0907},
                {"zone": "Gurgaon Cyber City",        "pincode": "122001", "lat": 28.4965, "lon": 77.0877},
                {"zone": "Faridabad Sector 15",       "pincode": "121007", "lat": 28.4089, "lon": 77.3178},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Connaught Place / Central", "pincode": "110001", "lat": 28.6280, "lon": 77.2190},
                {"zone": "South Delhi / Saket",       "pincode": "110017", "lat": 28.5244, "lon": 77.2066},
                {"zone": "Greater Kailash 1",         "pincode": "110048", "lat": 28.5494, "lon": 77.2501},
                {"zone": "Rohini Sector 3",           "pincode": "110085", "lat": 28.7041, "lon": 77.1025},
                {"zone": "Dwarka Sector 12",          "pincode": "110078", "lat": 28.5900, "lon": 77.0460},
                {"zone": "Lajpat Nagar",              "pincode": "110024", "lat": 28.5700, "lon": 77.2430},
                {"zone": "Preet Vihar / East Delhi",  "pincode": "110092", "lat": 28.6346, "lon": 77.2948},
                {"zone": "Noida Sector 18",           "pincode": "201301", "lat": 28.5706, "lon": 77.3211},
                {"zone": "Noida Sector 62",           "pincode": "201309", "lat": 28.6248, "lon": 77.3638},
                {"zone": "Gurgaon DLF Phase 2",       "pincode": "122002", "lat": 28.4807, "lon": 77.0907},
                {"zone": "Gurgaon Cyber City",        "pincode": "122001", "lat": 28.4965, "lon": 77.0877},
                {"zone": "Faridabad Sector 15",       "pincode": "121007", "lat": 28.4089, "lon": 77.3178},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Connaught Place / Central", "pincode": "110001", "lat": 28.6280, "lon": 77.2190},
                {"zone": "South Delhi / Saket",       "pincode": "110017", "lat": 28.5244, "lon": 77.2066},
                {"zone": "Greater Kailash 1",         "pincode": "110048", "lat": 28.5494, "lon": 77.2501},
                {"zone": "Rohini Sector 3",           "pincode": "110085", "lat": 28.7041, "lon": 77.1025},
                {"zone": "Dwarka Sector 12",          "pincode": "110078", "lat": 28.5900, "lon": 77.0460},
                {"zone": "Lajpat Nagar",              "pincode": "110024", "lat": 28.5700, "lon": 77.2430},
                {"zone": "Preet Vihar / East Delhi",  "pincode": "110092", "lat": 28.6346, "lon": 77.2948},
                {"zone": "Noida Sector 18",           "pincode": "201301", "lat": 28.5706, "lon": 77.3211},
                {"zone": "Noida Sector 62",           "pincode": "201309", "lat": 28.6248, "lon": 77.3638},
                {"zone": "Gurgaon DLF Phase 2",       "pincode": "122002", "lat": 28.4807, "lon": 77.0907},
                {"zone": "Gurgaon Cyber City",        "pincode": "122001", "lat": 28.4965, "lon": 77.0877},
                {"zone": "Faridabad Sector 15",       "pincode": "121007", "lat": 28.4089, "lon": 77.3178},
            ]},
        },
    },

    "hyderabad": {
        "name": "Hyderabad", "state": "Telangana",
        "lat": 17.3850, "lon": 78.4867, "pincode": "500001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Secunderabad",            "pincode": "500003", "lat": 17.4399, "lon": 78.4983},
                {"zone": "Banjara Hills Road 12",   "pincode": "500034", "lat": 17.4156, "lon": 78.4347},
                {"zone": "Jubilee Hills",           "pincode": "500033", "lat": 17.4324, "lon": 78.4070},
                {"zone": "Gachibowli",              "pincode": "500032", "lat": 17.4401, "lon": 78.3489},
                {"zone": "Hitech City / Madhapur",  "pincode": "500081", "lat": 17.4474, "lon": 78.3762},
                {"zone": "Kondapur",                "pincode": "500084", "lat": 17.4604, "lon": 78.3718},
                {"zone": "Kukatpally",              "pincode": "500072", "lat": 17.4849, "lon": 78.3978},
                {"zone": "LB Nagar",                "pincode": "500074", "lat": 17.3466, "lon": 78.5500},
                {"zone": "Ameerpet",                "pincode": "500016", "lat": 17.4375, "lon": 78.4485},
                {"zone": "Miyapur",                 "pincode": "500049", "lat": 17.4942, "lon": 78.3560},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Secunderabad",            "pincode": "500003", "lat": 17.4399, "lon": 78.4983},
                {"zone": "Banjara Hills Road 12",   "pincode": "500034", "lat": 17.4156, "lon": 78.4347},
                {"zone": "Jubilee Hills",           "pincode": "500033", "lat": 17.4324, "lon": 78.4070},
                {"zone": "Gachibowli",              "pincode": "500032", "lat": 17.4401, "lon": 78.3489},
                {"zone": "Hitech City / Madhapur",  "pincode": "500081", "lat": 17.4474, "lon": 78.3762},
                {"zone": "Kondapur",                "pincode": "500084", "lat": 17.4604, "lon": 78.3718},
                {"zone": "Kukatpally",              "pincode": "500072", "lat": 17.4849, "lon": 78.3978},
                {"zone": "LB Nagar",                "pincode": "500074", "lat": 17.3466, "lon": 78.5500},
                {"zone": "Ameerpet",                "pincode": "500016", "lat": 17.4375, "lon": 78.4485},
                {"zone": "Miyapur",                 "pincode": "500049", "lat": 17.4942, "lon": 78.3560},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Secunderabad",            "pincode": "500003", "lat": 17.4399, "lon": 78.4983},
                {"zone": "Banjara Hills Road 12",   "pincode": "500034", "lat": 17.4156, "lon": 78.4347},
                {"zone": "Jubilee Hills",           "pincode": "500033", "lat": 17.4324, "lon": 78.4070},
                {"zone": "Gachibowli",              "pincode": "500032", "lat": 17.4401, "lon": 78.3489},
                {"zone": "Hitech City / Madhapur",  "pincode": "500081", "lat": 17.4474, "lon": 78.3762},
                {"zone": "Kondapur",                "pincode": "500084", "lat": 17.4604, "lon": 78.3718},
                {"zone": "Kukatpally",              "pincode": "500072", "lat": 17.4849, "lon": 78.3978},
                {"zone": "LB Nagar",                "pincode": "500074", "lat": 17.3466, "lon": 78.5500},
                {"zone": "Ameerpet",                "pincode": "500016", "lat": 17.4375, "lon": 78.4485},
                {"zone": "Miyapur",                 "pincode": "500049", "lat": 17.4942, "lon": 78.3560},
            ]},
        },
    },

    "chennai": {
        "name": "Chennai", "state": "Tamil Nadu",
        "lat": 13.0827, "lon": 80.2707, "pincode": "600001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "George Town / Central",   "pincode": "600001", "lat": 13.0878, "lon": 80.2785},
                {"zone": "T. Nagar",                "pincode": "600017", "lat": 13.0418, "lon": 80.2341},
                {"zone": "Adyar",                   "pincode": "600020", "lat": 13.0012, "lon": 80.2565},
                {"zone": "Velachery",               "pincode": "600042", "lat": 12.9814, "lon": 80.2180},
                {"zone": "Anna Nagar West",         "pincode": "600040", "lat": 13.0850, "lon": 80.2101},
                {"zone": "Perambur / North Chennai","pincode": "600011", "lat": 13.1239, "lon": 80.2416},
                {"zone": "OMR / Sholinganallur",    "pincode": "600119", "lat": 12.9010, "lon": 80.2279},
                {"zone": "Tambaram",                "pincode": "600045", "lat": 12.9249, "lon": 80.1000},
                {"zone": "Porur",                   "pincode": "600116", "lat": 13.0382, "lon": 80.1574},
                {"zone": "Nungambakkam",            "pincode": "600034", "lat": 13.0569, "lon": 80.2425},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "George Town / Central",   "pincode": "600001", "lat": 13.0878, "lon": 80.2785},
                {"zone": "T. Nagar",                "pincode": "600017", "lat": 13.0418, "lon": 80.2341},
                {"zone": "Adyar",                   "pincode": "600020", "lat": 13.0012, "lon": 80.2565},
                {"zone": "Velachery",               "pincode": "600042", "lat": 12.9814, "lon": 80.2180},
                {"zone": "Anna Nagar West",         "pincode": "600040", "lat": 13.0850, "lon": 80.2101},
                {"zone": "Perambur / North Chennai","pincode": "600011", "lat": 13.1239, "lon": 80.2416},
                {"zone": "OMR / Sholinganallur",    "pincode": "600119", "lat": 12.9010, "lon": 80.2279},
                {"zone": "Tambaram",                "pincode": "600045", "lat": 12.9249, "lon": 80.1000},
                {"zone": "Porur",                   "pincode": "600116", "lat": 13.0382, "lon": 80.1574},
                {"zone": "Nungambakkam",            "pincode": "600034", "lat": 13.0569, "lon": 80.2425},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "George Town / Central",   "pincode": "600001", "lat": 13.0878, "lon": 80.2785},
                {"zone": "T. Nagar",                "pincode": "600017", "lat": 13.0418, "lon": 80.2341},
                {"zone": "Adyar",                   "pincode": "600020", "lat": 13.0012, "lon": 80.2565},
                {"zone": "Velachery",               "pincode": "600042", "lat": 12.9814, "lon": 80.2180},
                {"zone": "Anna Nagar West",         "pincode": "600040", "lat": 13.0850, "lon": 80.2101},
                {"zone": "Perambur / North Chennai","pincode": "600011", "lat": 13.1239, "lon": 80.2416},
                {"zone": "OMR / Sholinganallur",    "pincode": "600119", "lat": 12.9010, "lon": 80.2279},
                {"zone": "Tambaram",                "pincode": "600045", "lat": 12.9249, "lon": 80.1000},
                {"zone": "Porur",                   "pincode": "600116", "lat": 13.0382, "lon": 80.1574},
                {"zone": "Nungambakkam",            "pincode": "600034", "lat": 13.0569, "lon": 80.2425},
            ]},
        },
    },

    "pune": {
        "name": "Pune", "state": "Maharashtra",
        "lat": 18.5204, "lon": 73.8567, "pincode": "411001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Pune Camp",              "pincode": "411001", "lat": 18.5204, "lon": 73.8783},
                {"zone": "Shivajinagar / FC Road", "pincode": "411005", "lat": 18.5362, "lon": 73.8427},
                {"zone": "Kothrud",                "pincode": "411038", "lat": 18.5074, "lon": 73.8077},
                {"zone": "Baner / Pashan",         "pincode": "411045", "lat": 18.5590, "lon": 73.7868},
                {"zone": "Hinjewadi Phase 1",      "pincode": "411057", "lat": 18.5912, "lon": 73.7387},
                {"zone": "Viman Nagar",            "pincode": "411014", "lat": 18.5679, "lon": 73.9143},
                {"zone": "Aundh",                  "pincode": "411007", "lat": 18.5588, "lon": 73.8080},
                {"zone": "Hadapsar",               "pincode": "411028", "lat": 18.5018, "lon": 73.9260},
                {"zone": "Wakad",                  "pincode": "411057", "lat": 18.5990, "lon": 73.7602},
                {"zone": "NIBM / Kondhwa",         "pincode": "411048", "lat": 18.4681, "lon": 73.8936},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Pune Camp",              "pincode": "411001", "lat": 18.5204, "lon": 73.8783},
                {"zone": "Shivajinagar / FC Road", "pincode": "411005", "lat": 18.5362, "lon": 73.8427},
                {"zone": "Kothrud",                "pincode": "411038", "lat": 18.5074, "lon": 73.8077},
                {"zone": "Baner / Pashan",         "pincode": "411045", "lat": 18.5590, "lon": 73.7868},
                {"zone": "Hinjewadi Phase 1",      "pincode": "411057", "lat": 18.5912, "lon": 73.7387},
                {"zone": "Viman Nagar",            "pincode": "411014", "lat": 18.5679, "lon": 73.9143},
                {"zone": "Aundh",                  "pincode": "411007", "lat": 18.5588, "lon": 73.8080},
                {"zone": "Hadapsar",               "pincode": "411028", "lat": 18.5018, "lon": 73.9260},
                {"zone": "Wakad",                  "pincode": "411057", "lat": 18.5990, "lon": 73.7602},
                {"zone": "NIBM / Kondhwa",         "pincode": "411048", "lat": 18.4681, "lon": 73.8936},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Pune Camp",              "pincode": "411001", "lat": 18.5204, "lon": 73.8783},
                {"zone": "Shivajinagar / FC Road", "pincode": "411005", "lat": 18.5362, "lon": 73.8427},
                {"zone": "Kothrud",                "pincode": "411038", "lat": 18.5074, "lon": 73.8077},
                {"zone": "Baner / Pashan",         "pincode": "411045", "lat": 18.5590, "lon": 73.7868},
                {"zone": "Hinjewadi Phase 1",      "pincode": "411057", "lat": 18.5912, "lon": 73.7387},
                {"zone": "Viman Nagar",            "pincode": "411014", "lat": 18.5679, "lon": 73.9143},
                {"zone": "Aundh",                  "pincode": "411007", "lat": 18.5588, "lon": 73.8080},
                {"zone": "Hadapsar",               "pincode": "411028", "lat": 18.5018, "lon": 73.9260},
                {"zone": "Wakad",                  "pincode": "411057", "lat": 18.5990, "lon": 73.7602},
                {"zone": "NIBM / Kondhwa",         "pincode": "411048", "lat": 18.4681, "lon": 73.8936},
            ]},
        },
    },

    "kolkata": {
        "name": "Kolkata", "state": "West Bengal",
        "lat": 22.5726, "lon": 88.3639, "pincode": "700001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Central / BBD Bagh",        "pincode": "700001", "lat": 22.5730, "lon": 88.3524},
                {"zone": "South Kolkata / Gariahat",  "pincode": "700019", "lat": 22.5204, "lon": 88.3669},
                {"zone": "Ballygunge",                "pincode": "700019", "lat": 22.5355, "lon": 88.3636},
                {"zone": "Salt Lake Sector V",        "pincode": "700091", "lat": 22.5893, "lon": 88.4281},
                {"zone": "New Town / Rajarhat",       "pincode": "700156", "lat": 22.5886, "lon": 88.4782},
                {"zone": "Park Street / Esplanade",   "pincode": "700016", "lat": 22.5560, "lon": 88.3512},
                {"zone": "Dumdum / Airport Area",     "pincode": "700074", "lat": 22.6513, "lon": 88.3938},
                {"zone": "Howrah",                    "pincode": "711101", "lat": 22.5958, "lon": 88.2636},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Central / BBD Bagh",        "pincode": "700001", "lat": 22.5730, "lon": 88.3524},
                {"zone": "South Kolkata / Gariahat",  "pincode": "700019", "lat": 22.5204, "lon": 88.3669},
                {"zone": "Ballygunge",                "pincode": "700019", "lat": 22.5355, "lon": 88.3636},
                {"zone": "Salt Lake Sector V",        "pincode": "700091", "lat": 22.5893, "lon": 88.4281},
                {"zone": "New Town / Rajarhat",       "pincode": "700156", "lat": 22.5886, "lon": 88.4782},
                {"zone": "Park Street / Esplanade",   "pincode": "700016", "lat": 22.5560, "lon": 88.3512},
                {"zone": "Dumdum / Airport Area",     "pincode": "700074", "lat": 22.6513, "lon": 88.3938},
                {"zone": "Howrah",                    "pincode": "711101", "lat": 22.5958, "lon": 88.2636},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Central / BBD Bagh",        "pincode": "700001", "lat": 22.5730, "lon": 88.3524},
                {"zone": "South Kolkata / Gariahat",  "pincode": "700019", "lat": 22.5204, "lon": 88.3669},
                {"zone": "Ballygunge",                "pincode": "700019", "lat": 22.5355, "lon": 88.3636},
                {"zone": "Salt Lake Sector V",        "pincode": "700091", "lat": 22.5893, "lon": 88.4281},
                {"zone": "New Town / Rajarhat",       "pincode": "700156", "lat": 22.5886, "lon": 88.4782},
                {"zone": "Park Street / Esplanade",   "pincode": "700016", "lat": 22.5560, "lon": 88.3512},
                {"zone": "Dumdum / Airport Area",     "pincode": "700074", "lat": 22.6513, "lon": 88.3938},
                {"zone": "Howrah",                    "pincode": "711101", "lat": 22.5958, "lon": 88.2636},
            ]},
        },
    },

    "ahmedabad": {
        "name": "Ahmedabad", "state": "Gujarat",
        "lat": 23.0225, "lon": 72.5714, "pincode": "380001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Relief Road / Old City",   "pincode": "380001", "lat": 23.0225, "lon": 72.5714},
                {"zone": "Vastrapur / IIM Road",     "pincode": "380015", "lat": 23.0310, "lon": 72.5301},
                {"zone": "Prahlad Nagar",            "pincode": "380015", "lat": 23.0105, "lon": 72.5061},
                {"zone": "SG Highway / Satellite",   "pincode": "380054", "lat": 23.0152, "lon": 72.5085},
                {"zone": "Bopal / South Ahmedabad",  "pincode": "380058", "lat": 23.0059, "lon": 72.4690},
                {"zone": "Maninagar",                "pincode": "380008", "lat": 22.9915, "lon": 72.6063},
                {"zone": "Naranpura",                "pincode": "380013", "lat": 23.0596, "lon": 72.5624},
                {"zone": "Gota",                     "pincode": "382481", "lat": 23.1101, "lon": 72.5372},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Relief Road / Old City",   "pincode": "380001", "lat": 23.0225, "lon": 72.5714},
                {"zone": "Vastrapur / IIM Road",     "pincode": "380015", "lat": 23.0310, "lon": 72.5301},
                {"zone": "Prahlad Nagar",            "pincode": "380015", "lat": 23.0105, "lon": 72.5061},
                {"zone": "SG Highway / Satellite",   "pincode": "380054", "lat": 23.0152, "lon": 72.5085},
                {"zone": "Bopal / South Ahmedabad",  "pincode": "380058", "lat": 23.0059, "lon": 72.4690},
                {"zone": "Maninagar",                "pincode": "380008", "lat": 22.9915, "lon": 72.6063},
                {"zone": "Naranpura",                "pincode": "380013", "lat": 23.0596, "lon": 72.5624},
                {"zone": "Gota",                     "pincode": "382481", "lat": 23.1101, "lon": 72.5372},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Relief Road / Old City",   "pincode": "380001", "lat": 23.0225, "lon": 72.5714},
                {"zone": "Vastrapur / IIM Road",     "pincode": "380015", "lat": 23.0310, "lon": 72.5301},
                {"zone": "Prahlad Nagar",            "pincode": "380015", "lat": 23.0105, "lon": 72.5061},
                {"zone": "SG Highway / Satellite",   "pincode": "380054", "lat": 23.0152, "lon": 72.5085},
                {"zone": "Bopal / South Ahmedabad",  "pincode": "380058", "lat": 23.0059, "lon": 72.4690},
                {"zone": "Maninagar",                "pincode": "380008", "lat": 22.9915, "lon": 72.6063},
                {"zone": "Naranpura",                "pincode": "380013", "lat": 23.0596, "lon": 72.5624},
                {"zone": "Gota",                     "pincode": "382481", "lat": 23.1101, "lon": 72.5372},
            ]},
        },
    },

    # ── Tier 2 ────────────────────────────────────────────────────────────────

    "jaipur": {
        "name": "Jaipur", "state": "Rajasthan",
        "lat": 26.9124, "lon": 75.7873, "pincode": "302001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Pink City / Walled City", "pincode": "302001", "lat": 26.9239, "lon": 75.8267},
                {"zone": "Malviya Nagar",           "pincode": "302017", "lat": 26.8524, "lon": 75.8092},
                {"zone": "Vaishali Nagar",          "pincode": "302021", "lat": 26.9206, "lon": 75.7362},
                {"zone": "Mansarovar",              "pincode": "302020", "lat": 26.8620, "lon": 75.7543},
                {"zone": "Raja Park / C-Scheme",    "pincode": "302004", "lat": 26.9025, "lon": 75.8244},
                {"zone": "Sodala / Shyam Nagar",    "pincode": "302019", "lat": 26.9261, "lon": 75.7678},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Pink City / Walled City", "pincode": "302001", "lat": 26.9239, "lon": 75.8267},
                {"zone": "Malviya Nagar",           "pincode": "302017", "lat": 26.8524, "lon": 75.8092},
                {"zone": "Vaishali Nagar",          "pincode": "302021", "lat": 26.9206, "lon": 75.7362},
                {"zone": "Mansarovar",              "pincode": "302020", "lat": 26.8620, "lon": 75.7543},
                {"zone": "Raja Park / C-Scheme",    "pincode": "302004", "lat": 26.9025, "lon": 75.8244},
                {"zone": "Sodala / Shyam Nagar",    "pincode": "302019", "lat": 26.9261, "lon": 75.7678},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Pink City / Walled City", "pincode": "302001", "lat": 26.9239, "lon": 75.8267},
                {"zone": "Malviya Nagar",           "pincode": "302017", "lat": 26.8524, "lon": 75.8092},
                {"zone": "Vaishali Nagar",          "pincode": "302021", "lat": 26.9206, "lon": 75.7362},
                {"zone": "Mansarovar",              "pincode": "302020", "lat": 26.8620, "lon": 75.7543},
                {"zone": "Raja Park / C-Scheme",    "pincode": "302004", "lat": 26.9025, "lon": 75.8244},
                {"zone": "Sodala / Shyam Nagar",    "pincode": "302019", "lat": 26.9261, "lon": 75.7678},
            ]},
        },
    },

    "lucknow": {
        "name": "Lucknow", "state": "Uttar Pradesh",
        "lat": 26.8467, "lon": 80.9462, "pincode": "226001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Hazratganj / Central", "pincode": "226001", "lat": 26.8467, "lon": 80.9462},
                {"zone": "Gomti Nagar",          "pincode": "226010", "lat": 26.8381, "lon": 80.9797},
                {"zone": "Aliganj",              "pincode": "226024", "lat": 26.8870, "lon": 80.9493},
                {"zone": "Indira Nagar",         "pincode": "226016", "lat": 26.8814, "lon": 81.0047},
                {"zone": "Vikas Nagar",          "pincode": "226022", "lat": 26.9124, "lon": 80.9801},
                {"zone": "Mahanagar",            "pincode": "226006", "lat": 26.8677, "lon": 80.9264},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Hazratganj / Central", "pincode": "226001", "lat": 26.8467, "lon": 80.9462},
                {"zone": "Gomti Nagar",          "pincode": "226010", "lat": 26.8381, "lon": 80.9797},
                {"zone": "Aliganj",              "pincode": "226024", "lat": 26.8870, "lon": 80.9493},
                {"zone": "Indira Nagar",         "pincode": "226016", "lat": 26.8814, "lon": 81.0047},
                {"zone": "Vikas Nagar",          "pincode": "226022", "lat": 26.9124, "lon": 80.9801},
                {"zone": "Mahanagar",            "pincode": "226006", "lat": 26.8677, "lon": 80.9264},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Hazratganj / Central", "pincode": "226001", "lat": 26.8467, "lon": 80.9462},
                {"zone": "Gomti Nagar",          "pincode": "226010", "lat": 26.8381, "lon": 80.9797},
                {"zone": "Aliganj",              "pincode": "226024", "lat": 26.8870, "lon": 80.9493},
                {"zone": "Indira Nagar",         "pincode": "226016", "lat": 26.8814, "lon": 81.0047},
                {"zone": "Vikas Nagar",          "pincode": "226022", "lat": 26.9124, "lon": 80.9801},
                {"zone": "Mahanagar",            "pincode": "226006", "lat": 26.8677, "lon": 80.9264},
            ]},
        },
    },

    "chandigarh": {
        "name": "Chandigarh", "state": "Punjab/Haryana",
        "lat": 30.7333, "lon": 76.7794, "pincode": "160001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Sector 17 / City Centre", "pincode": "160017", "lat": 30.7410, "lon": 76.7840},
                {"zone": "Sector 35",               "pincode": "160035", "lat": 30.7214, "lon": 76.7689},
                {"zone": "Sector 22",               "pincode": "160022", "lat": 30.7346, "lon": 76.7746},
                {"zone": "Mohali Phase 7",          "pincode": "160062", "lat": 30.7127, "lon": 76.7177},
                {"zone": "Zirakpur",                "pincode": "140603", "lat": 30.6451, "lon": 76.8198},
                {"zone": "Panchkula Sector 5",      "pincode": "134109", "lat": 30.6945, "lon": 76.8530},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Sector 17 / City Centre", "pincode": "160017", "lat": 30.7410, "lon": 76.7840},
                {"zone": "Sector 35",               "pincode": "160035", "lat": 30.7214, "lon": 76.7689},
                {"zone": "Sector 22",               "pincode": "160022", "lat": 30.7346, "lon": 76.7746},
                {"zone": "Mohali Phase 7",          "pincode": "160062", "lat": 30.7127, "lon": 76.7177},
                {"zone": "Zirakpur",                "pincode": "140603", "lat": 30.6451, "lon": 76.8198},
                {"zone": "Panchkula Sector 5",      "pincode": "134109", "lat": 30.6945, "lon": 76.8530},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Sector 17 / City Centre", "pincode": "160017", "lat": 30.7410, "lon": 76.7840},
                {"zone": "Sector 35",               "pincode": "160035", "lat": 30.7214, "lon": 76.7689},
                {"zone": "Sector 22",               "pincode": "160022", "lat": 30.7346, "lon": 76.7746},
                {"zone": "Mohali Phase 7",          "pincode": "160062", "lat": 30.7127, "lon": 76.7177},
                {"zone": "Zirakpur",                "pincode": "140603", "lat": 30.6451, "lon": 76.8198},
                {"zone": "Panchkula Sector 5",      "pincode": "134109", "lat": 30.6945, "lon": 76.8530},
            ]},
        },
    },

    "surat": {
        "name": "Surat", "state": "Gujarat",
        "lat": 21.1702, "lon": 72.8311, "pincode": "395001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Ring Road / Citylight", "pincode": "395007", "lat": 21.1702, "lon": 72.8311},
                {"zone": "Adajan",                "pincode": "395009", "lat": 21.2029, "lon": 72.7997},
                {"zone": "Vesu",                  "pincode": "395007", "lat": 21.1328, "lon": 72.7843},
                {"zone": "Varachha",              "pincode": "395006", "lat": 21.2148, "lon": 72.8649},
                {"zone": "Piplod",                "pincode": "395007", "lat": 21.1424, "lon": 72.7902},
                {"zone": "Katargam",              "pincode": "395004", "lat": 21.2253, "lon": 72.8359},
            ]},
            "zepto": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Ring Road / Citylight", "pincode": "395007", "lat": 21.1702, "lon": 72.8311},
                {"zone": "Adajan",                "pincode": "395009", "lat": 21.2029, "lon": 72.7997},
                {"zone": "Vesu",                  "pincode": "395007", "lat": 21.1328, "lon": 72.7843},
                {"zone": "Varachha",              "pincode": "395006", "lat": 21.2148, "lon": 72.8649},
                {"zone": "Piplod",                "pincode": "395007", "lat": 21.1424, "lon": 72.7902},
                {"zone": "Katargam",              "pincode": "395004", "lat": 21.2253, "lon": 72.8359},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Ring Road / Citylight", "pincode": "395007", "lat": 21.1702, "lon": 72.8311},
                {"zone": "Adajan",                "pincode": "395009", "lat": 21.2029, "lon": 72.7997},
                {"zone": "Vesu",                  "pincode": "395007", "lat": 21.1328, "lon": 72.7843},
                {"zone": "Varachha",              "pincode": "395006", "lat": 21.2148, "lon": 72.8649},
                {"zone": "Piplod",                "pincode": "395007", "lat": 21.1424, "lon": 72.7902},
                {"zone": "Katargam",              "pincode": "395004", "lat": 21.2253, "lon": 72.8359},
            ]},
        },
    },

    "indore": {
        "name": "Indore", "state": "Madhya Pradesh",
        "lat": 22.7196, "lon": 75.8577, "pincode": "452001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Central",         "pincode": "452001", "lat": 22.7196, "lon": 75.8577},
                {"zone": "Vijay Nagar",               "pincode": "452010", "lat": 22.7536, "lon": 75.8935},
                {"zone": "Palasia / Geeta Bhawan",    "pincode": "452001", "lat": 22.7282, "lon": 75.8798},
                {"zone": "Scheme 78 / Nipania",       "pincode": "452010", "lat": 22.7413, "lon": 75.9275},
                {"zone": "Rajwada / Chhota Bangarda", "pincode": "452006", "lat": 22.7178, "lon": 75.8355},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Central",         "pincode": "452001", "lat": 22.7196, "lon": 75.8577},
                {"zone": "Vijay Nagar",               "pincode": "452010", "lat": 22.7536, "lon": 75.8935},
                {"zone": "Palasia / Geeta Bhawan",    "pincode": "452001", "lat": 22.7282, "lon": 75.8798},
                {"zone": "Scheme 78 / Nipania",       "pincode": "452010", "lat": 22.7413, "lon": 75.9275},
                {"zone": "Rajwada / Chhota Bangarda", "pincode": "452006", "lat": 22.7178, "lon": 75.8355},
            ]},
        },
    },

    "nagpur": {
        "name": "Nagpur", "state": "Maharashtra",
        "lat": 21.1458, "lon": 79.0882, "pincode": "440001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Sitabuldi / Central",     "pincode": "440012", "lat": 21.1458, "lon": 79.0882},
                {"zone": "Dharampeth",              "pincode": "440010", "lat": 21.1414, "lon": 79.0659},
                {"zone": "Ramdaspeth",              "pincode": "440010", "lat": 21.1340, "lon": 79.0784},
                {"zone": "Sadar",                   "pincode": "440001", "lat": 21.1620, "lon": 79.0910},
                {"zone": "Mankapur / Manish Nagar", "pincode": "440015", "lat": 21.1209, "lon": 79.0441},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Sitabuldi / Central",     "pincode": "440012", "lat": 21.1458, "lon": 79.0882},
                {"zone": "Dharampeth",              "pincode": "440010", "lat": 21.1414, "lon": 79.0659},
                {"zone": "Ramdaspeth",              "pincode": "440010", "lat": 21.1340, "lon": 79.0784},
                {"zone": "Sadar",                   "pincode": "440001", "lat": 21.1620, "lon": 79.0910},
                {"zone": "Mankapur / Manish Nagar", "pincode": "440015", "lat": 21.1209, "lon": 79.0441},
            ]},
        },
    },

    "kochi": {
        "name": "Kochi", "state": "Kerala",
        "lat": 9.9312, "lon": 76.2673, "pincode": "682001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Ernakulam",  "pincode": "682011", "lat": 9.9816,  "lon": 76.2998},
                {"zone": "Kakkanad / Infopark",  "pincode": "682030", "lat": 10.0159, "lon": 76.3419},
                {"zone": "Kaloor",               "pincode": "682017", "lat": 10.0008, "lon": 76.2987},
                {"zone": "Vyttila",              "pincode": "682019", "lat": 9.9617,  "lon": 76.3094},
                {"zone": "Fort Kochi",           "pincode": "682001", "lat": 9.9577,  "lon": 76.2424},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "MG Road / Ernakulam",  "pincode": "682011", "lat": 9.9816,  "lon": 76.2998},
                {"zone": "Kakkanad / Infopark",  "pincode": "682030", "lat": 10.0159, "lon": 76.3419},
                {"zone": "Kaloor",               "pincode": "682017", "lat": 10.0008, "lon": 76.2987},
                {"zone": "Vyttila",              "pincode": "682019", "lat": 9.9617,  "lon": 76.3094},
                {"zone": "Fort Kochi",           "pincode": "682001", "lat": 9.9577,  "lon": 76.2424},
            ]},
        },
    },

    "coimbatore": {
        "name": "Coimbatore", "state": "Tamil Nadu",
        "lat": 11.0168, "lon": 76.9558, "pincode": "641001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "RS Puram / Central",         "pincode": "641002", "lat": 11.0168, "lon": 76.9558},
                {"zone": "Gandhipuram",                "pincode": "641012", "lat": 11.0218, "lon": 76.9695},
                {"zone": "Peelamedu / Airport Road",   "pincode": "641004", "lat": 11.0280, "lon": 77.0276},
                {"zone": "Saibaba Colony",             "pincode": "641011", "lat": 11.0034, "lon": 76.9392},
                {"zone": "Tidel Park / Hopes College", "pincode": "641035", "lat": 11.0478, "lon": 76.9984},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "RS Puram / Central",         "pincode": "641002", "lat": 11.0168, "lon": 76.9558},
                {"zone": "Gandhipuram",                "pincode": "641012", "lat": 11.0218, "lon": 76.9695},
                {"zone": "Peelamedu / Airport Road",   "pincode": "641004", "lat": 11.0280, "lon": 77.0276},
                {"zone": "Saibaba Colony",             "pincode": "641011", "lat": 11.0034, "lon": 76.9392},
                {"zone": "Tidel Park / Hopes College", "pincode": "641035", "lat": 11.0478, "lon": 76.9984},
            ]},
        },
    },

    "visakhapatnam": {
        "name": "Visakhapatnam", "state": "Andhra Pradesh",
        "lat": 17.6868, "lon": 83.2185, "pincode": "530001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Dwaraka Nagar",         "pincode": "530016", "lat": 17.7241, "lon": 83.3160},
                {"zone": "MVP Colony",            "pincode": "530017", "lat": 17.7285, "lon": 83.3415},
                {"zone": "Jagadamba / Old Town",  "pincode": "530001", "lat": 17.6868, "lon": 83.2185},
                {"zone": "Gajuwaka",              "pincode": "530026", "lat": 17.6820, "lon": 83.1951},
                {"zone": "Madhurawada / IT Hub",  "pincode": "530048", "lat": 17.7933, "lon": 83.3765},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Dwaraka Nagar",         "pincode": "530016", "lat": 17.7241, "lon": 83.3160},
                {"zone": "MVP Colony",            "pincode": "530017", "lat": 17.7285, "lon": 83.3415},
                {"zone": "Jagadamba / Old Town",  "pincode": "530001", "lat": 17.6868, "lon": 83.2185},
                {"zone": "Gajuwaka",              "pincode": "530026", "lat": 17.6820, "lon": 83.1951},
                {"zone": "Madhurawada / IT Hub",  "pincode": "530048", "lat": 17.7933, "lon": 83.3765},
            ]},
        },
    },

    "bhopal": {
        "name": "Bhopal", "state": "Madhya Pradesh",
        "lat": 23.2599, "lon": 77.4126, "pincode": "462001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "New Market / MP Nagar", "pincode": "462011", "lat": 23.2330, "lon": 77.4327},
                {"zone": "Arera Colony",          "pincode": "462016", "lat": 23.2002, "lon": 77.4381},
                {"zone": "Kolar Road",            "pincode": "462042", "lat": 23.1674, "lon": 77.4471},
                {"zone": "Bairagarh",             "pincode": "462030", "lat": 23.2890, "lon": 77.3439},
                {"zone": "Shahpura",              "pincode": "462039", "lat": 23.1893, "lon": 77.4727},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "New Market / MP Nagar", "pincode": "462011", "lat": 23.2330, "lon": 77.4327},
                {"zone": "Arera Colony",          "pincode": "462016", "lat": 23.2002, "lon": 77.4381},
                {"zone": "Kolar Road",            "pincode": "462042", "lat": 23.1674, "lon": 77.4471},
                {"zone": "Bairagarh",             "pincode": "462030", "lat": 23.2890, "lon": 77.3439},
                {"zone": "Shahpura",              "pincode": "462039", "lat": 23.1893, "lon": 77.4727},
            ]},
        },
    },

    "vadodara": {
        "name": "Vadodara", "state": "Gujarat",
        "lat": 22.3072, "lon": 73.1812, "pincode": "390001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Alkapuri / RC Dutt Road", "pincode": "390007", "lat": 22.3072, "lon": 73.1812},
                {"zone": "Gotri",                   "pincode": "390021", "lat": 22.3331, "lon": 73.1568},
                {"zone": "Manjalpur",               "pincode": "390011", "lat": 22.2678, "lon": 73.1924},
                {"zone": "Akota",                   "pincode": "390020", "lat": 22.3162, "lon": 73.1686},
                {"zone": "Waghodia Road / Harni",   "pincode": "390006", "lat": 22.3312, "lon": 73.2070},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Alkapuri / RC Dutt Road", "pincode": "390007", "lat": 22.3072, "lon": 73.1812},
                {"zone": "Gotri",                   "pincode": "390021", "lat": 22.3331, "lon": 73.1568},
                {"zone": "Manjalpur",               "pincode": "390011", "lat": 22.2678, "lon": 73.1924},
                {"zone": "Akota",                   "pincode": "390020", "lat": 22.3162, "lon": 73.1686},
                {"zone": "Waghodia Road / Harni",   "pincode": "390006", "lat": 22.3312, "lon": 73.2070},
            ]},
        },
    },

    "patna": {
        "name": "Patna", "state": "Bihar",
        "lat": 25.5941, "lon": 85.1376, "pincode": "800001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Gandhi Maidan / Central", "pincode": "800001", "lat": 25.6093, "lon": 85.1235},
                {"zone": "Boring Road",             "pincode": "800001", "lat": 25.6131, "lon": 85.0988},
                {"zone": "Kankarbagh",              "pincode": "800020", "lat": 25.5924, "lon": 85.1524},
                {"zone": "Bailey Road",             "pincode": "800014", "lat": 25.6225, "lon": 85.0821},
                {"zone": "Patliputra Colony",       "pincode": "800013", "lat": 25.6351, "lon": 85.0753},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Gandhi Maidan / Central", "pincode": "800001", "lat": 25.6093, "lon": 85.1235},
                {"zone": "Boring Road",             "pincode": "800001", "lat": 25.6131, "lon": 85.0988},
                {"zone": "Kankarbagh",              "pincode": "800020", "lat": 25.5924, "lon": 85.1524},
                {"zone": "Bailey Road",             "pincode": "800014", "lat": 25.6225, "lon": 85.0821},
                {"zone": "Patliputra Colony",       "pincode": "800013", "lat": 25.6351, "lon": 85.0753},
            ]},
        },
    },

    "nashik": {
        "name": "Nashik", "state": "Maharashtra",
        "lat": 19.9975, "lon": 73.7898, "pincode": "422001",
        "platforms": {
            "blinkit": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Gangapur Road / Canada Corner", "pincode": "422005", "lat": 20.0035, "lon": 73.7652},
                {"zone": "College Road",                  "pincode": "422005", "lat": 20.0138, "lon": 73.7803},
                {"zone": "Cidco / New Nashik",            "pincode": "422009", "lat": 19.9754, "lon": 73.7979},
                {"zone": "Indira Nagar",                  "pincode": "422009", "lat": 19.9641, "lon": 73.8186},
            ]},
            "instamart": {"zones": [  # TODO: verify dark-store coordinates
                {"zone": "Gangapur Road / Canada Corner", "pincode": "422005", "lat": 20.0035, "lon": 73.7652},
                {"zone": "College Road",                  "pincode": "422005", "lat": 20.0138, "lon": 73.7803},
                {"zone": "Cidco / New Nashik",            "pincode": "422009", "lat": 19.9754, "lon": 73.7979},
                {"zone": "Indira Nagar",                  "pincode": "422009", "lat": 19.9641, "lon": 73.8186},
            ]},
        },
    },
}

# ── Convenience lookups ────────────────────────────────────────────────────────

ALL_CITY_SLUGS: list[str] = list(CITIES.keys())

PLATFORM_CITIES: dict[str, list[str]] = {
    "blinkit":   [s for s, c in CITIES.items() if "blinkit"   in c["platforms"]],
    "zepto":     [s for s, c in CITIES.items() if "zepto"     in c["platforms"]],
    "instamart": [s for s, c in CITIES.items() if "instamart" in c["platforms"]],
}

ALL_THREE: list[str] = [s for s, c in CITIES.items() if len(c["platforms"]) == 3]
