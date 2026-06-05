"""持久化存储 — Supabase（生产）或 CSV（本地），多用户隔离"""
import os
import hashlib
import pandas as pd

_url = os.environ.get("SUPABASE_URL", "")
_key = os.environ.get("SUPABASE_ANON_KEY", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "quant2024")
MODE = "supabase" if _url and _key else "csv"

# 确保缓存目录存在（新部署时 cache/ 不在 git 中）
_cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(_cache_dir, exist_ok=True)

_supabase = None

if MODE == "supabase":
    try:
        from supabase import create_client, Client
        _supabase: Client = create_client(_url, _key)
    except ImportError:
        MODE = "csv"  # supabase 未安装，回退到 CSV
        print("[supabase_client] supabase package not installed, falling back to CSV mode")


def _hash_pw(password: str, salt: bytes = None) -> str:
    """PBKDF2-SHA256 密码哈希（含盐值）"""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return salt.hex() + "$" + dk.hex()

def _check_pw(stored: str, password: str) -> bool:
    """验证密码是否匹配存储的哈希"""
    try:
        salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100000)
        return dk.hex() == dk_hex
    except Exception:
        return False

def verify_login(name: str, password: str) -> bool:
    """验证用户名和密码"""
    try:
        if MODE == "supabase":
            resp = _supabase.table("users").select("password_hash").eq("username", name).execute()
            if resp.data:
                return _check_pw(resp.data[0]["password_hash"], password)
        else:
            _load_csv_users()
            if name in _CSV_USERS:
                return _check_pw(_CSV_USERS[name], password)
    except Exception:
        pass
    return _check_pw(_hash_pw(APP_PASSWORD), password)


# ═══════════════════════════════════════════════════
# 公共接口（CSV 和 Supabase 统一）
# ═══════════════════════════════════════════════════

def load_investment_history(user_id: str) -> pd.DataFrame:
    if MODE == "csv":
        return _csv_load(user_id)
    return _supabase_load(user_id)


def save_investment_round(user_id: str, records: list[dict]) -> bool:
    if MODE == "csv":
        return _csv_save(user_id, records)
    return _supabase_save(user_id, records)


def close_prev_holdings(user_id: str, execute_date: str, prices: dict[str, float],
                        skip_same_date: bool = False) -> tuple[int, float]:
    """关闭持仓并返回 (关闭数量, 加权收益率)。
    skip_same_date=True 时跳过与 execute_date 同日的持仓（自动调仓用）。"""
    if MODE == "csv":
        return _csv_close(user_id, execute_date, prices, skip_same_date)
    return _supabase_close(user_id, execute_date, prices, skip_same_date)


def user_exists(username: str) -> bool:
    """检查用户是否存在"""
    if MODE == "csv":
        return _csv_user_exists(username)
    return _supabase_user_exists(username)


def register_user(username: str, password: str) -> bool:
    """注册新用户"""
    if MODE == "csv":
        return _csv_register(username, password)
    return _supabase_register(username, password)


# ═══════════════════════════════════════════════════
# Supabase 实现
# ═══════════════════════════════════════════════════

def _supabase_load(user_id: str) -> pd.DataFrame:
    try:
        resp = _supabase.table("investments").select("*").eq("user_id", user_id).order("execute_date", desc=False).execute()
    except Exception as e:
        print(f"[supabase] SELECT (load) failed: {e}", flush=True)
        return pd.DataFrame()
    if not resp.data:
        return pd.DataFrame()
    df = pd.DataFrame(resp.data)
    for col in ["id", "user_id"]:
        if col in df.columns:
            df = df.drop(columns=[col])
    if "execute_date" in df.columns:
        df["execute_date"] = pd.to_datetime(df["execute_date"])
    if "exit_date" in df.columns:
        df["exit_date"] = pd.to_datetime(df["exit_date"])
    return df


def _supabase_save(user_id: str, records: list[dict]) -> bool:
    for r in records:
        r["user_id"] = user_id
    try:
        _supabase.table("investments").insert(records).execute()
    except Exception as e:
        print(f"[supabase] INSERT failed: {e}", flush=True)
        raise RuntimeError(f"Supabase INSERT 失败: {e}") from e
    return True


def _supabase_close(user_id: str, execute_date: str, prices: dict[str, float],
                    skip_same_date: bool = False) -> tuple[int, float]:
    try:
        resp = _supabase.table("investments").select("*").eq("user_id", user_id).eq("status", "holding").execute()
    except Exception as e:
        print(f"[supabase] SELECT (close) failed: {e}", flush=True)
        raise RuntimeError(f"Supabase 查询持仓失败: {e}") from e
    if not resp.data:
        return 0, 0.0
    count = 0
    total_return = 0.0
    total_weight = 0.0
    for row in resp.data:
        row_ex_date = str(row.get("execute_date", ""))[:10]
        if skip_same_date and row_ex_date == execute_date:
            continue
        stock = row["stock"]
        if stock in prices:
            entry = row["entry_price"]
            exit_p = prices[stock]
            if entry and entry > 0 and exit_p > 0:
                ret = round((exit_p / entry - 1) * 100, 2)
                try:
                    _supabase.table("investments").update({
                        "exit_price": round(exit_p, 2),
                        "return_pct": ret,
                        "status": "closed",
                        "exit_date": execute_date,
                    }).eq("id", row["id"]).execute()
                except Exception as e:
                    print(f"[supabase] UPDATE (close) failed for stock {stock}: {e}", flush=True)
                    raise RuntimeError(f"Supabase 更新持仓 {stock} 失败: {e}") from e
                count += 1
                total_return += ret * row.get("weight", 0.1)
                total_weight += row.get("weight", 0.1)
    weighted_ret = round(total_return / total_weight, 2) if total_weight > 0 else 0.0
    return count, weighted_ret


# ═══════════════════════════════════════════════════
# CSV 本地实现（开发/离线备用）
# ═══════════════════════════════════════════════════

import config as cfg

def _csv_path() -> str:
    import config as cfg
    return os.path.join(cfg.CACHE_DIR, "investment_history.csv")


_CSV_USERS = {}  # 内存缓存：用户名 → 密码哈希（本地开发用）

def _csv_user_exists(username: str) -> bool:
    _load_csv_users()
    return username in _CSV_USERS

def _csv_register(username: str, password: str) -> bool:
    _load_csv_users()
    if username in _CSV_USERS:
        return False
    _CSV_USERS[username] = _hash_pw(password)
    _save_csv_users()
    return True

def _load_csv_users():
    path = os.path.join(cfg.CACHE_DIR, "users.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, dtype=str)
        for _, row in df.iterrows():
            _CSV_USERS[row["username"]] = row["password_hash"]

def _save_csv_users():
    path = os.path.join(cfg.CACHE_DIR, "users.csv")
    pd.DataFrame([{"username": u, "password_hash": h} for u, h in _CSV_USERS.items()]).to_csv(path, index=False)

# Supabase 实现
def _supabase_user_exists(username: str) -> bool:
    try:
        resp = _supabase.table("users").select("username").eq("username", username).execute()
        return bool(resp.data)
    except Exception:
        return _csv_user_exists(username)

def _supabase_register(username: str, password: str) -> bool:
    try:
        _supabase.table("users").insert({"username": username, "password_hash": _hash_pw(password)}).execute()
        return True
    except Exception:
        return _csv_register(username, password)


def _csv_load(user_id: str) -> pd.DataFrame:
    path = _csv_path()
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"stock": str})
    if "user_id" not in df.columns:
        df["user_id"] = "default"
    df = df[df["user_id"] == user_id]
    if "execute_date" in df.columns and len(df) > 0:
        df["execute_date"] = pd.to_datetime(df["execute_date"])
    if "exit_date" in df.columns and len(df) > 0:
        df["exit_date"] = pd.to_datetime(df["exit_date"])
    return df.sort_values("execute_date") if not df.empty else df


def _csv_save(user_id: str, records: list[dict]) -> bool:
    path = _csv_path()
    for r in records:
        r["user_id"] = user_id
    df_new = pd.DataFrame(records)
    if os.path.exists(path):
        df_old = pd.read_csv(path, dtype={"stock": str})
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new
    df_all.to_csv(path, index=False)
    return True


def _csv_close(user_id: str, execute_date: str, prices: dict[str, float],
               skip_same_date: bool = False) -> tuple[int, float]:
    path = _csv_path()
    if not os.path.exists(path):
        return 0, 0.0
    df = pd.read_csv(path, dtype={"stock": str})
    if "user_id" not in df.columns:
        df["user_id"] = "default"

    mask = (df["user_id"] == user_id) & (df.get("status", "holding") == "holding")
    if skip_same_date:
        mask = mask & (df["execute_date"] != execute_date)
    if not mask.any():
        return 0, 0.0

    count = 0
    total_return = 0.0
    total_weight = 0.0
    for idx in df[mask].index:
        stock = df.at[idx, "stock"]
        if stock in prices:
            entry = df.at[idx, "entry_price"]
            exit_p = prices[stock]
            if pd.notna(entry) and entry > 0 and exit_p > 0:
                ret = round((exit_p / entry - 1) * 100, 2)
                df.at[idx, "exit_price"] = round(exit_p, 2)
                df.at[idx, "return_pct"] = ret
                df.at[idx, "status"] = "closed"
                df.at[idx, "exit_date"] = execute_date
                count += 1
                total_return += ret * float(df.at[idx, "weight"])
                total_weight += float(df.at[idx, "weight"])

    df.to_csv(path, index=False)
    weighted_ret = round(total_return / total_weight, 2) if total_weight > 0 else 0.0
    return count, weighted_ret
