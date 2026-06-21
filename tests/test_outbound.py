from unittest.mock import patch
import pytest
from physiobot.outbound import Outbound
from physiobot.config import MetaConfig

def test_send_template_unconfigured(config):
    # When meta is not configured, it logs and returns fallback text
    out = Outbound(config)
    reply = out.send_template("9199", "welcome_greeting", clinic_name="Test Clinic")
    assert "Test Clinic" in reply

def test_send_template_interactive_configured(config):
    # Set meta as configured
    meta = MetaConfig(
        token="EAAnFG...",
        phone_number_id="1108484",
        verify_token="verify",
        app_secret="secret",
        use_templates=False
    )
    # Rebuild config with configured MetaConfig
    config_configured = config._replace(meta=meta) if hasattr(config, "_replace") else config
    
    # We can override the meta config using patch or simple assignment
    out = Outbound(config_configured)
    object.__setattr__(out.config, "meta", meta) # since Config is frozen
    
    with patch("httpx.post") as mock_post:
        # Mock successful post response
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        
        reply = out.send_template("9199", "request_service_mode")
        
        # Verify the mock POST was made
        assert mock_post.called
        args, kwargs = mock_post.call_args
        # Verify it sent interactive button payload
        json_payload = kwargs["json"]
        assert json_payload["type"] == "interactive"
        assert json_payload["interactive"]["type"] == "button"
        assert "clinic_visit" in str(json_payload)
        
        assert "clinic_visit" in reply
