from .database import get_db_connection

def add_links(user_id: str, links: list[str]):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Simple insert, assuming all are ACTIVE
    for link in links:
        cursor.execute(
            "INSERT INTO links (user_id, url, status) VALUES (?, ?, ?)",
            (str(user_id), link, 'ACTIVE')
        )
        
    conn.commit()
    conn.close()

def get_active_links(user_id: str) -> list[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT url FROM links WHERE user_id = ? AND status = 'ACTIVE'",
        (str(user_id),)
    )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [row["url"] for row in rows]

def count_active_links(user_id: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM links WHERE user_id = ? AND status = 'ACTIVE'", (str(user_id),))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def count_all_links(user_id: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM links WHERE user_id = ?", (str(user_id),))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_next_active_link(user_id: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT url FROM links WHERE user_id = ? AND status = 'ACTIVE' LIMIT 1",
        (str(user_id),)
    )
    row = cursor.fetchone()
    conn.close()
    return row["url"] if row else None

def get_all_links(user_id: str) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, url, status, last_checked, fail_count FROM links WHERE user_id = ?",
        (str(user_id),)
    )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def delete_link(link_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM links WHERE id = ?", (link_id,))
    
    conn.commit()
    conn.close()

def get_all_active_links_global() -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, user_id, url, status, fail_count FROM links WHERE status = 'ACTIVE'"
    )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def mark_link_flagged(link_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE links SET status = 'FLAGGED', fail_count = fail_count + 1, last_checked = CURRENT_TIMESTAMP WHERE id = ?",
        (link_id,)
    )
    
    conn.commit()
    conn.close()

def update_last_checked(link_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE links SET last_checked = CURRENT_TIMESTAMP WHERE id = ?",
        (link_id,)
    )
    
    conn.commit()
    conn.close()

def increment_fail_count(link_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE links SET fail_count = fail_count + 1, last_checked = CURRENT_TIMESTAMP WHERE id = ?",
        (link_id,)
    )
    
    conn.commit()
    conn.close()

def reset_fail_count(link_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE links SET fail_count = 0, last_checked = CURRENT_TIMESTAMP WHERE id = ?",
        (link_id,)
    )
    
    conn.commit()
    conn.close()