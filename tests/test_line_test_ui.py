from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from mori.core import AppError


def panel():
    from mori.line_test_ui import render_line_test
    render_line_test({'LINE_CHANNEL_ACCESS_TOKEN':'fake-test-token','LINE_RECIPIENT_ID':'C123456'})


def test_line_test_is_explicit_and_retry_is_idempotent():
    with patch('mori.line_test_ui.LineClient') as factory:
        at = AppTest.from_function(panel).run()
        client = factory.return_value
        assert not client.push.called
        assert '示範' in at.text[0].value and '120' in at.text[0].value
        client.push.side_effect = [AppError('LINE 發送結果尚未確認'), 'accepted']
        at.button(key='send_line_test').click().run()
        assert at.error
        first = client.push.call_args.args
        at.button(key='send_line_test').click().run()
        assert not at.exception
        assert client.push.call_args.args == first
        assert first[0] == 'C123456'
        assert at.button(key='send_line_test').disabled
        assert at.success and 'API 已接受' in at.success[0].value
        assert client.push.call_count == 2


def test_unauthorized_token_error_is_not_reported_as_quota():
    from mori.notifications import LineClient
    import pytest
    response = type('Response', (), {'status_code':401,'ok':False,'headers':{}})()
    session = type('Session', (), {'post':lambda *args, **kwargs:response})()
    with pytest.raises(AppError, match='權杖驗證失敗') as exc:
        LineClient('secret-must-not-be-shown',session).push('C123456','test','retry')
    assert '不是額度不足' in str(exc.value)
    assert 'secret-must-not-be-shown' not in str(exc.value)
