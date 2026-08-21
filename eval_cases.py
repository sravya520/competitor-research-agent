"""Regression cases built from failures this system actually had.

Each case exists because the system once got it wrong. Rather than trying to
define the single "correct" competitor list for a company — which reasonable
analysts would disagree about — each case asserts something narrower and
checkable: it must stop here, or it must not return these.

Add a case whenever a new failure is found. That is what stops the same bug
coming back.

Cases marked `informational` are reported but do not fail the suite. They
cover behaviour that genuinely varies between runs — live search results
change, and an assertion that depends on them is testing the web rather than
this code. A test that flakes for reasons unrelated to your change teaches
you to ignore it, which is worse than not having it.
"""

CASES = [
    {
        "id": "ambiguous-name-should-stop",
        "company": "sprout design pvt ltd",
        "url": None,
        "expect_stop": True,
        "informational": True,
        "why": (
            "Several unrelated companies share this name (a UK firm, a US "
            "branding studio, and a separately registered entity in "
            "Ghaziabad, India). Guessing produced confident reports about "
            "the wrong company three separate times, so stopping is the "
            "behaviour we want. Informational because the outcome depends on "
            "what live search surfaces that day: some runs find no single "
            "match and stop, others find one registered entity and proceed. "
            "Neither is a code defect — it is why the URL anchor exists."
        ),
    },
    {
        "id": "small-studio-url-anchored",
        "company": "Sprout Design",
        "url": "https://sproutdesign.framer.website/",
        "expect_stop": False,
        "min_competitors": 2,
        # A two-person studio. These are all real companies, but all of them
        # are far too large or in the wrong category to be peers.
        "must_not_include": [
            "IDEO",
            "Fuseproject",
            "Smart Design",
            "Whipsaw",
            "Delve",
            "Tata Elxsi",
            "Desmania",
            "Elephant Design",
            "Designit",
            "Ogilvy",
            "500 Designs",
            "Step 3D",
            "CADmando",
        ],
        "why": (
            "Early runs returned global design giants, then CAD-drafting "
            "firms, then generic categories. All three were wrong for a "
            "two-person startup-focused studio."
        ),
    },
    {
        "id": "small-startup-scale-match",
        "company": "Cheerio AI",
        "url": None,
        "expect_stop": False,
        "min_competitors": 2,
        # Enterprise CDPs and data-infrastructure platforms — the user's own
        # verdict on these was "not at all useful".
        "must_not_include": [
            "Hightouch",
            "Twilio Segment",
            "Segment",
            "Capillary Technologies",
            "Zeotap",
            "CustomerLabs",
            "Salesforce",
            "HubSpot",
        ],
        "why": (
            "A generic query surfaced large enterprise customer-data "
            "platforms rather than peers of a small Bangalore startup."
        ),
    },
    {
        "id": "well-known-company-sanity",
        "company": "Duolingo",
        "url": None,
        "expect_stop": False,
        "min_competitors": 3,
        # An easy case. If this breaks, something fundamental is wrong.
        "should_include_any_of": [
            "Babbel",
            "Busuu",
            "Memrise",
            "Rosetta Stone",
            "Pimsleur",
        ],
        "why": "A well-documented company with obvious competitors — a floor, not a target.",
    },
]
