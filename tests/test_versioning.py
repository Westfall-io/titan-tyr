import pytest

from src.versioning import InvalidVersion, Version


class TestParse:
    def test_stable(self):
        v = Version.parse("1.2.3")
        assert (v.major, v.minor, v.patch, v.prerelease) == (1, 2, 3, None)

    def test_rc(self):
        v = Version.parse("1.2.3-rc4")
        assert (v.major, v.minor, v.patch, v.prerelease) == (1, 2, 3, "rc4")

    def test_zero_initial(self):
        assert Version.parse("0.1.0").major == 0

    @pytest.mark.parametrize(
        "bad",
        ["", "1", "1.2", "1.2.3.4", "v1.2.3", "1.2.3-alpha", "1.2.3+build", "1.2.3-rc"],
    )
    def test_invalid(self, bad):
        with pytest.raises(InvalidVersion):
            Version.parse(bad)

    def test_disallow_prerelease(self):
        with pytest.raises(InvalidVersion):
            Version.parse("1.2.3-rc1", allow_prerelease=False)


class TestFormat:
    def test_stable_str(self):
        assert str(Version(1, 2, 3)) == "1.2.3"

    def test_rc_str(self):
        assert str(Version(1, 2, 3, "rc2")) == "1.2.3-rc2"


class TestOrdering:
    def test_patch_bumps(self):
        assert Version(1, 0, 0) < Version(1, 0, 1)

    def test_minor_beats_patch(self):
        assert Version(1, 0, 5) < Version(1, 1, 0)

    def test_major_beats_minor(self):
        assert Version(1, 9, 9) < Version(2, 0, 0)

    def test_stable_beats_rc(self):
        assert Version(1, 3, 0, "rc1") < Version(1, 3, 0)
        assert Version(1, 3, 0, "rc99") < Version(1, 3, 0)

    def test_rc_numeric(self):
        assert Version(1, 3, 0, "rc1") < Version(1, 3, 0, "rc2")
        assert Version(1, 3, 0, "rc9") < Version(1, 3, 0, "rc10")  # numeric, not lex

    def test_max_picks_stable_over_rc(self):
        assert max(Version(1, 3, 0, "rc2"), Version(1, 3, 0)) == Version(1, 3, 0)

    def test_equality(self):
        assert Version(1, 2, 3) == Version(1, 2, 3)
        assert Version(1, 2, 3, "rc1") == Version(1, 2, 3, "rc1")
        assert Version(1, 2, 3) != Version(1, 2, 3, "rc1")

    def test_hashable(self):
        s = {Version(1, 2, 3), Version(1, 2, 3), Version(1, 2, 3, "rc1")}
        assert len(s) == 2


class TestStable:
    def test_stable_strips_prerelease(self):
        assert Version(1, 3, 0, "rc2").stable() == Version(1, 3, 0)

    def test_stable_idempotent(self):
        assert Version(1, 3, 0).stable() == Version(1, 3, 0)

    def test_is_prerelease(self):
        assert Version(1, 3, 0, "rc1").is_prerelease
        assert not Version(1, 3, 0).is_prerelease


class TestNotImplemented:
    def test_lt_other_type(self):
        assert Version(1, 0, 0).__lt__("nope") is NotImplemented

    def test_eq_other_type(self):
        assert Version(1, 0, 0).__eq__("nope") is NotImplemented
