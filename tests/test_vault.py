import copy
import json
import pytest
from cryptography.fernet import Fernet
from mori.core import AppError
from mori.vault import CredentialVault, resolve_credentials

class Store:
    def __init__(self):
        self.data = {}
        self.sha = None
    def read(self, path, default):
        return copy.deepcopy(self.data or default), self.sha
    def write(self, path, data, sha, **kwargs):
        assert sha == self.sha
        self.data = copy.deepcopy(data)
        self.sha = 'next'


def test_encrypted_round_trip_and_preserve_blank():
    store = Store()
    key = Fernet.generate_key().decode()
    vault = CredentialVault(store, key)
    vault.update({'META_ACCESS_TOKEN': 'private-token', 'META_API_VERSION': 'v26.0'})
    assert 'private-token' not in json.dumps(store.data)
    assert 'META_ACCESS_TOKEN' not in json.dumps(store.data)
    vault.update({'META_ACCESS_TOKEN': '', 'META_API_VERSION': 'v27.0'})
    values, _ = vault.read()
    assert values == {'META_ACCESS_TOKEN': 'private-token', 'META_API_VERSION': 'v27.0'}
    resolved = resolve_credentials({'META_ACCESS_TOKEN': 'old', 'GOOGLE_CLIENT_ID': 'existing'}, store, key)
    assert resolved['META_ACCESS_TOKEN'] == 'private-token'
    assert resolved['GOOGLE_CLIENT_ID'] == 'existing'


def test_wrong_key_tamper_and_missing_key_fail_closed():
    store = Store()
    key = Fernet.generate_key().decode()
    vault = CredentialVault(store, key)
    vault.update({'META_ACCESS_TOKEN': 'private-token'})
    original = copy.deepcopy(store.data)
    with pytest.raises(AppError):
        CredentialVault(store, Fernet.generate_key().decode()).update({'META_ACCESS_TOKEN': 'new'})
    assert store.data == original
    with pytest.raises(AppError):
        resolve_credentials({}, store, '')
    store.data['ciphertext'] = store.data['ciphertext'][:-4] + 'abcd'
    with pytest.raises(AppError):
        vault.read()


def test_invalid_fields_and_masks_rejected():
    vault = CredentialVault(Store(), Fernet.generate_key().decode())
    with pytest.raises(AppError):
        vault.update({'STATE_TOKEN': 'must-not-store-bootstrap'})
    with pytest.raises(AppError):
        vault.update({'META_ACCESS_TOKEN': '********'})
    with pytest.raises(AppError):
        CredentialVault(Store(), 'invalid-key')


def test_legacy_secrets_still_work_without_vault():
    assert resolve_credentials({'META_ACCESS_TOKEN': 'legacy'}, Store(), '') == {'META_ACCESS_TOKEN': 'legacy'}


@pytest.mark.parametrize("version", [None, ""])
def test_meta_version_is_managed_without_manual_input(version):
    from mori.providers import MetaProvider, DEFAULT_META_API_VERSION
    credentials = {"META_ACCESS_TOKEN": "test-token"}
    if version is not None:
        credentials["META_API_VERSION"] = version
    assert MetaProvider(credentials).root == "https://graph.facebook.com/" + DEFAULT_META_API_VERSION
