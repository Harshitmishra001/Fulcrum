import pytest
import sqlite3
import os
from src.db.database import get_db_connection, init_db

def test_foreign_keys_enforced():
    db_path = "test_fk.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db(db_path)
    
    conn = get_db_connection(db_path)
    
    with pytest.raises(sqlite3.IntegrityError):
        # Attempting to insert a relation where fact_a_id and fact_b_id do not exist
        conn.execute("""
            INSERT INTO relations (id, fact_a_id, fact_b_id, relation_type)
            VALUES (?, ?, ?, ?)
        """, ("rel_1", "non_existent_1", "non_existent_2", "corroboration"))
        
    conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)
