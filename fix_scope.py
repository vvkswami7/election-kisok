with open("backend.py", "r") as f:
    content = f.read()

# Slice the file into its structural blocks
imports_part, app_part = content.split('app = FastAPI', 1)
app_part = 'app = FastAPI' + app_part
app_block, rest = app_part.split('# Global state', 1)
globals_lifespan, routes = rest.split('def retrieve_context', 1)

# Reassemble: Imports -> Globals & Lifespan -> App & Middleware -> Routes
new_content = imports_part + '# Global state' + globals_lifespan + app_block + 'def retrieve_context' + routes

with open("backend.py", "w") as f:
    f.write(new_content)
    
print("✓ Backend scope reordered successfully!")
