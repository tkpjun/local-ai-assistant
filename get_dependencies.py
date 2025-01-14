import sqlite3

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("codebase.db")
cursor = conn.cursor()

# Function to recursively unroll dependencies
def get_dependencies(identifier):
    cursor.execute("SELECT id FROM snippets WHERE identifier = ?", (identifier,))
    snippet_id = cursor.fetchone()
    if not snippet_id:
        return []

    dependencies = []
    stack = [snippet_id[0]]

    while stack:
        current_id = stack.pop()
        cursor.execute("SELECT dependency_id FROM dependencies WHERE snippet_id = ?", (current_id,))
        results = cursor.fetchall()
        for dep_id in results:
            cursor.execute("SELECT identifier FROM snippets WHERE id = ?", (dep_id[0],))
            dep_identifier = cursor.fetchone()
            if dep_identifier:
                dependencies.append(dep_identifier[0])
                stack.append(dep_id[0])

    return dependencies

print(get_dependencies("get_dependencies"))