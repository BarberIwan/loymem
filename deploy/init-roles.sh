#!/bin/sh
# Runs once when the database volume is created: the owner role (migrations,
# BYPASSRLS) and the app role (no BYPASSRLS), as in the tests.
set -e
psql -v ON_ERROR_STOP=1 -U postgres <<SQL
create role loymem_owner login password '${LOYMEM_OWNER_PASSWORD}' bypassrls;
create role loymem_app login password '${LOYMEM_APP_PASSWORD}';
create database loymem owner loymem_owner;
\c loymem
alter schema public owner to loymem_owner;
grant usage on schema public to loymem_app;
SQL
