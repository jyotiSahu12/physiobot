import hashlib
import hmac

from physiobot import webhook


def test_verify_subscription_ok():
    assert webhook.verify_subscription("subscribe", "tok", "tok")


def test_verify_subscription_bad_token():
    assert not webhook.verify_subscription("subscribe", "wrong", "tok")


def test_verify_signature_no_secret_accepts():
    assert webhook.verify_signature(b"body", "", "")


def test_verify_signature_valid():
    secret = "s3cret"
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert webhook.verify_signature(body, sig, secret)


def test_verify_signature_invalid():
    assert not webhook.verify_signature(b"body", "sha256=deadbeef", "s3cret")


def test_parse_incoming_text():
    payload = {
        "entry": [{
            "changes": [{
                "value": {"messages": [
                    {"type": "text", "from": "9199", "text": {"body": "hi"}}
                ]}
            }]
        }]
    }
    assert webhook.parse_incoming(payload) == [("9199", "hi")]


def test_parse_incoming_ignores_status():
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}
    assert webhook.parse_incoming(payload) == []


def test_parse_incoming_interactive():
    # Test button reply
    payload_btn = {
        "entry": [{
            "changes": [{
                "value": {"messages": [
                    {
                        "type": "interactive",
                        "from": "9199",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "home_visit", "title": "Home Visit"}
                        }
                    }
                ]}
            }]
        }]
    }
    assert webhook.parse_incoming(payload_btn) == [("9199", "Home Visit")]

    # Test list reply
    payload_list = {
        "entry": [{
            "changes": [{
                "value": {"messages": [
                    {
                        "type": "interactive",
                        "from": "9199",
                        "interactive": {
                            "type": "list_reply",
                            "list_reply": {"id": "neck", "title": "Neck"}
                        }
                    }
                ]}
            }]
        }]
    }
    assert webhook.parse_incoming(payload_list) == [("9199", "Neck")]
