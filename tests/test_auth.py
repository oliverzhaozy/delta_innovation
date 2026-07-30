from tests.conftest import DEFAULT_TEST_PASSWORD, login


def test_login_success_grants_access(client, make_person):
    username = make_person()
    resp = login(client, username)
    assert resp.status_code == 200
    # A login-protected page now renders instead of redirecting.
    assert client.get("/password").status_code == 200


def test_wrong_password_rejected_generically(client, make_person):
    username = make_person()
    resp = login(client, username, password="not-the-password")
    assert b"Invalid credentials." in resp.data
    assert client.get("/password").status_code == 302


def test_unknown_user_gets_same_message(client, make_person):
    make_person()
    resp = login(client, "no_such_user")
    assert b"Invalid credentials." in resp.data


def test_logout_ends_session(client, make_person):
    username = make_person()
    login(client, username)
    client.post("/logout")
    assert client.get("/password").status_code == 302


def test_session_rotated_on_login(client, make_person):
    # A pre-auth session value must not survive authentication (fixation).
    username = make_person()
    with client.session_transaction() as sess:
        sess["marker"] = "pre-auth"
    login(client, username)
    with client.session_transaction() as sess:
        assert "marker" not in sess
        assert "_user_id" in sess


def test_must_change_pw_locks_everything_else(client, make_person):
    username = make_person(must_change_pw=True)
    login(client, username)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/password" in resp.headers["Location"]
    assert client.get("/password").status_code == 200


def test_change_password_flow(client, make_person):
    username = make_person(must_change_pw=True)
    login(client, username)
    resp = client.post(
        "/password",
        data={
            "current_password": DEFAULT_TEST_PASSWORD,
            "new_password": "a-brand-new-password",
            "confirm": "a-brand-new-password",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Lock is lifted and the new password works on a fresh session.
    assert client.get("/", follow_redirects=False).status_code == 200
    client.post("/logout")
    assert b"Invalid credentials." not in login(client, username, "a-brand-new-password").data


def test_short_new_password_rejected(client, make_person):
    username = make_person()
    login(client, username)
    resp = client.post(
        "/password",
        data={
            "current_password": DEFAULT_TEST_PASSWORD,
            "new_password": "short",
            "confirm": "short",
        },
    )
    assert b"at least 12 characters" in resp.data


def test_next_redirect_must_be_relative(client, make_person):
    username = make_person()
    resp = client.post(
        "/login?next=https://evil.example.com/",
        data={"username": username, "password": DEFAULT_TEST_PASSWORD},
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]
