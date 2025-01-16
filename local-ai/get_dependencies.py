import sys
from lib.aggregating import get_dependencies

id = sys.argv[1]
print(get_dependencies(id, 10000))