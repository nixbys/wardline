import pytest

from wardline.common.errors import AccessDeniedError
from wardline.governance import abac, rbac
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER, User


def _user(role: str) -> User:
    return User(email=f"{role}@example.com", role=role)


def test_require_role_allows_matching_role():
    rbac.require_role(_user(ROLE_ADMIN), ROLE_ADMIN)  # does not raise


def test_require_role_denies_non_matching_role():
    with pytest.raises(AccessDeniedError):
        rbac.require_role(_user(ROLE_VIEWER), ROLE_ADMIN)


def test_require_role_accepts_any_of_several_roles():
    rbac.require_role(_user(ROLE_ANALYST), ROLE_ADMIN, ROLE_ANALYST)


@pytest.mark.parametrize("license", ["CC-BY-SA-4.0", "us-gov-open-data", None])
def test_abac_allows_non_internal_licenses_for_any_role(license):
    assert abac.check_access(_user(ROLE_VIEWER), license)


def test_abac_denies_internal_only_for_viewer():
    assert not abac.check_access(_user(ROLE_VIEWER), "internal-only")


def test_abac_allows_internal_only_for_analyst_and_admin():
    assert abac.check_access(_user(ROLE_ANALYST), "internal-only")
    assert abac.check_access(_user(ROLE_ADMIN), "internal-only")
