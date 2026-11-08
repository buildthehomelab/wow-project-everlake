-- luacheck for client/addons (CI). The game's API is a huge set of globals, so global access is not checked;
-- syntax errors, unused locals, shadowing and unreachable code still are.
std = "lua51"
max_line_length = false
ignore = { "11.", "12.", "13.", "212/self" }
