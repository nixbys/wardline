from wardline.common.security import generate_api_key, lookup_key_for_index, verify_api_key


def test_generated_key_verifies_against_its_own_hash():
    plaintext, key_hash = generate_api_key()
    assert verify_api_key(plaintext, key_hash)


def test_wrong_key_does_not_verify():
    _plaintext, key_hash = generate_api_key()
    assert not verify_api_key("crn_totally-wrong-key", key_hash)


def test_lookup_hash_is_deterministic():
    plaintext, _key_hash = generate_api_key()
    assert lookup_key_for_index(plaintext) == lookup_key_for_index(plaintext)


def test_two_generated_keys_are_distinct():
    key_a, _ = generate_api_key()
    key_b, _ = generate_api_key()
    assert key_a != key_b
