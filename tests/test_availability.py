from hetzner_watch.availability import Offer, describe, extract, format_price, iter_offers, missing_types


def available_keys(offers):
    return sorted(k for k, o in offers.items() if o.available)


def test_filters_types_on_all_locations(mixed):
    offers = extract(mixed, ["cx43", "cx33", "cax31", "cax21"])
    assert sorted(offers) == [
        "cax21@fsn1", "cax21@hel1", "cax21@nbg1",
        "cax31@fsn1", "cax31@hel1", "cax31@nbg1",
        "cx33@fsn1", "cx33@hel1", "cx33@nbg1",
        "cx43@fsn1", "cx43@nbg1",
    ]  # fmt: skip
    assert available_keys(offers) == ["cax21@hel1", "cx33@fsn1", "cx43@nbg1"]


def test_deprecated_location_is_ignored(mixed):
    # cx43@hel1 est marqué disponible mais déprécié
    assert "cx43@hel1" not in extract(mixed, ["cx43"])


def test_filters_locations(mixed):
    offers = extract(mixed, ["cx43", "cx33", "cax21"], ["fsn1", "hel1"])
    assert sorted(offers) == ["cax21@fsn1", "cax21@hel1", "cx33@fsn1", "cx33@hel1", "cx43@fsn1"]
    assert available_keys(offers) == ["cax21@hel1", "cx33@fsn1"]


def test_non_eu_location_with_empty_filter(mixed):
    assert available_keys(extract(mixed, ["cpx22"])) == ["cpx22@ash"]


def test_name_case_is_normalized(mixed):
    mixed[2]["name"] = "CX43"
    mixed[2]["locations"][1]["name"] = "NBG1"
    assert "cx43@nbg1" in extract(mixed, ["cx43"])


def test_missing_types(mixed):
    assert missing_types(mixed, ["cx43", "cx42", "ccx13"]) == ["cx42", "ccx13"]  # ccx13 déprécié partout


def test_offer_fields(mixed):
    offer = extract(mixed, ["cx43"])["cx43@nbg1"]
    assert offer == Offer("cx43", "nbg1", True, "9.4900", 8, 16.0, "x86")


def test_format_price():
    assert format_price("9.4900") == "9,49 € HT/mois"
    assert format_price("12.4950") == "12,50 € HT/mois"
    assert format_price(None) == ""
    assert format_price("n/a") == ""


def test_describe():
    assert (
        describe(Offer("cx43", "fsn1", True, "9.4900", 8, 16.0, "x86"))
        == "CX43 à fsn1 (8 vCPU, 16 Go, x86) : 9,49 € HT/mois"
    )
    assert describe(Offer("cax11", "hel1", True)) == "CAX11 à hel1"


def test_robust_to_odd_entries():
    weird = [
        {"name": "cx43"},  # pas de locations
        {"name": "", "locations": [{"name": "fsn1", "available": True, "deprecation": None}]},
        {"name": "cx33", "locations": ["fsn1", {"available": True, "deprecation": None}]},
        {"name": "cx23", "locations": [{"name": "fsn1", "available": "yes", "deprecation": None}]},
    ]
    offers = list(iter_offers(weird))
    assert offers == [Offer("cx23", "fsn1", False)]  # "yes" n'est pas True
