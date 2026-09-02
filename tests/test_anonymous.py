"""Reading the public API without credentials."""

from __future__ import annotations

import pytest
import responses

from biblindex_client import BiblIndexClient, BiblIndexError

from .conftest import BASE_URL, make_hydra_collection


@pytest.fixture
def anonymous() -> BiblIndexClient:
    """A client built with no credentials at all."""
    return BiblIndexClient(BASE_URL)


def test_client_without_credentials_is_anonymous(anonymous: BiblIndexClient) -> None:
    assert anonymous.isAnonymous


def test_any_credential_makes_the_client_authenticated() -> None:
    """A partial set is a configuration mistake, not a request to go anonymous."""
    assert not BiblIndexClient(BASE_URL, username="u").isAnonymous
    assert not BiblIndexClient(BASE_URL, clientSecret="s").isAnonymous


@responses.activate
def test_anonymous_request_sends_no_authorization_and_no_token_call(
    anonymous: BiblIndexClient,
) -> None:
    """The public endpoints answer 200 to an unauthenticated GET."""
    responses.get(f"{BASE_URL}/api/books", json=make_hydra_collection([], total_items=107))

    result = anonymous.request("/api/books", {"page": 1})

    assert len(result) == 107
    assert len(responses.calls) == 1
    assert "Authorization" not in responses.calls[0].request.headers


@responses.activate
def test_anonymous_401_says_credentials_are_needed(anonymous: BiblIndexClient) -> None:
    """A bearer-less 401 must not be retried as if a token had expired."""
    responses.get(f"{BASE_URL}/api/quotations", status=401, json={})

    with pytest.raises(BiblIndexError) as error:
        anonymous.request("/api/quotations", {})

    message = str(error.value)
    assert "without credentials" in message
    assert "not public" in message
    # No token round-trip was attempted.
    assert len(responses.calls) == 1


@responses.activate
def test_anonymous_client_can_read_the_openapi_document(
    anonymous: BiblIndexClient,
) -> None:
    """Filter validation works with no credentials, since the doc is public."""
    responses.get(
        f"{BASE_URL}/api/docs.jsonopenapi",
        json={"paths": {"/api/works": {"get": {"parameters": [{"name": "author"}]}}}},
    )

    assert anonymous.filtersFor("/api/works") == frozenset({"author"})


@pytest.mark.parametrize("operation", ["fetchTokens", "refreshTokens"])
def test_token_operations_refuse_an_anonymous_client(
    anonymous: BiblIndexClient, operation: str
) -> None:
    with pytest.raises(BiblIndexError) as error:
        getattr(anonymous, operation)()

    assert f"{operation}() needs credentials" in str(error.value)


@responses.activate
def test_credentialed_client_still_sends_the_bearer(client: BiblIndexClient) -> None:
    """The authenticated path is unchanged."""
    responses.post(
        f"{BASE_URL}/api/token",
        json={"access_token": "A", "refresh_token": "R", "expires_in": 3600},
    )
    responses.get(f"{BASE_URL}/api/books", json=make_hydra_collection([]))

    client.request("/api/books", {})

    assert responses.calls[1].request.headers["Authorization"] == "Bearer A"


@responses.activate
def test_anonymous_403_does_not_claim_a_token_was_valid(
    anonymous: BiblIndexClient,
) -> None:
    """Live behaviour: /api/quotations answers 403, not 401, to a bare GET.

    The credentialed message reasons from "the same token works on /api/works",
    which is nonsense when no token was sent.
    """
    responses.get(f"{BASE_URL}/api/quotations", status=403, json={})

    with pytest.raises(BiblIndexError) as error:
        anonymous.request("/api/quotations", {})

    message = str(error.value)
    assert "token itself is valid" not in message
    assert "without credentials" in message
    # The role is still worth flagging as the next hurdle, not the current one.
    assert "ROLE_API_CLIENT" in message


@responses.activate
def test_anonymous_403_outside_the_corpus_omits_the_role_note(
    anonymous: BiblIndexClient,
) -> None:
    """Only the corpus resources are known to need the role; do not guess."""
    responses.get(f"{BASE_URL}/api/genres", status=403, json={})

    with pytest.raises(BiblIndexError) as error:
        anonymous.request("/api/genres", {})

    assert "ROLE_API_CLIENT" not in str(error.value)
    assert "without credentials" in str(error.value)
