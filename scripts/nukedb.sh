./synctl stop

rm homeserver.db

./synctl start

./scripts/register_new_matrix_user -u test -p jupiter -a -c homeserver.yaml http://localhost:8008
./scripts/register_new_matrix_user -u test2 -p jupiter -a -c homeserver.yaml http://localhost:8008
./scripts/register_new_matrix_user -u test3 -p jupiter -a -c homeserver.yaml http://localhost:8008
./scripts/register_new_matrix_user -u test4 -p jupiter -a -c homeserver.yaml http://localhost:8008
./scripts/register_new_matrix_user -u test5 -p jupiter -a -c homeserver.yaml http://localhost:8008

tail -f homeserver.log
