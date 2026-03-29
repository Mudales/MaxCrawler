import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

LOGIN_URL = "https://www.max.co.il/api/login/login"
HOMEPAGE_URL = "https://www.max.co.il/homepage"


@dataclass
class AccountConfig:
    username: str
    password: str
    owner: str


@dataclass
class Config:
    accounts: list
    cav: str
    user_agent: str
    db_path: str

    # backward-compat shims for code that still reads cfg.username / cfg.password
    @property
    def username(self) -> str:
        return self.accounts[0].username if self.accounts else ""

    @property
    def password(self) -> str:
        return self.accounts[0].password if self.accounts else ""


def load_config() -> Config:
    accounts: list[AccountConfig] = []

    # Numbered format: MAX_USERNAME_1, MAX_PASSWORD_1, MAX_OWNER_1, ...
    i = 1
    while True:
        u = os.getenv(f"MAX_USERNAME_{i}", "")
        p = os.getenv(f"MAX_PASSWORD_{i}", "")
        o = os.getenv(f"MAX_OWNER_{i}", f"חשבון {i}")
        if not u or not p:
            break
        accounts.append(AccountConfig(username=u, password=p, owner=o))
        i += 1

    # Backward-compat: plain MAX_USERNAME / MAX_PASSWORD
    if not accounts:
        u = os.getenv("MAX_USERNAME", "")
        p = os.getenv("MAX_PASSWORD", "")
        o = os.getenv("MAX_OWNER", "רפאל")
        if u and p:
            accounts.append(AccountConfig(username=u, password=p, owner=o))

    if not accounts:
        raise ValueError(
            "No MAX accounts configured. Add MAX_USERNAME_1 / MAX_PASSWORD_1 to .env"
        )

    return Config(
        accounts=accounts,
        cav=os.getenv("MAX_CAV", "V4.209-RC.14.88"),
        user_agent=os.getenv(
            "MAX_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        ),
        db_path=os.getenv("DB_PATH", "transactions.db"),
    )
