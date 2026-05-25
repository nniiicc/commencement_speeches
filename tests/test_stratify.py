from commencement.stage0_frame.stratify import proportional_allocation


def test_proportional_allocation_sums_to_sample_size():
    strata = {"a": 100, "b": 200, "c": 700}
    out = proportional_allocation(strata, sample_size=100)
    assert sum(out.values()) == 100
    assert out["c"] >= out["b"] >= out["a"]


def test_proportional_allocation_handles_zero_total():
    out = proportional_allocation({"a": 0, "b": 0}, sample_size=10)
    assert all(v == 0 for v in out.values())


def test_proportional_allocation_remainder_goes_to_largest_fractional():
    strata = {"a": 1, "b": 1, "c": 1}
    out = proportional_allocation(strata, sample_size=4)
    assert sum(out.values()) == 4
    assert max(out.values()) == 2


def test_proportional_allocation_300_realistic_shape():
    strata = {f"s{i}": 100 * (i + 1) for i in range(20)}
    out = proportional_allocation(strata, sample_size=300)
    assert sum(out.values()) == 300
