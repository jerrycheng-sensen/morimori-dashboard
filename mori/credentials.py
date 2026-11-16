import os


def credentials_from_env():
    names = ["META_ACCESS_TOKEN", "META_API_VERSION", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
             "GOOGLE_REFRESH_TOKEN", "GOOGLE_LOGIN_CUSTOMER_ID", "GOOGLE_API_VERSION",
             "GOOGLE_DEVELOPER_TOKEN", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_RECIPIENT_ID", "LINE_RECIPIENTS_JSON"]
    return {name: os.environ.get(name, "") for name in names}
