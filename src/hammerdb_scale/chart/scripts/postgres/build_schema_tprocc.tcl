#!/bin/tclsh
# Build the TPROC-C schema on PostgreSQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set pg_port $::env(PG_PORT)

set tprocc_user $::env(TPROCC_USER)
set tprocc_password $::env(TPROCC_PASSWORD)
set tprocc_database_name $::env(TPROCC_DATABASE_NAME)
set tprocc_build_virtual_users $::env(TPROCC_BUILD_VIRTUAL_USERS)
set warehouses $::env(WAREHOUSES)

foreach var {USERNAME PASSWORD HOST PG_PORT TPROCC_DATABASE_NAME WAREHOUSES TPROCC_BUILD_VIRTUAL_USERS} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-C SCHEMA BUILD FOR POSTGRESQL"
puts "  Host: $host:$pg_port"
puts "  Database: $tprocc_database_name"
puts "  Warehouses: $warehouses"
puts "  Build Virtual Users: $tprocc_build_virtual_users"

dbset db pg
dbset bm TPC-C

# Connection
diset connection pg_host $host
diset connection pg_port $pg_port
if {[info exists ::env(PG_SSLMODE)]} {
    diset connection pg_sslmode $::env(PG_SSLMODE)
}

# The superuser creates the schema owner role and the database.
diset tpcc pg_superuser $username
diset tpcc pg_superuserpass $password
diset tpcc pg_defaultdbase postgres

diset tpcc pg_user $tprocc_user
diset tpcc pg_pass $tprocc_password
diset tpcc pg_dbase $tprocc_database_name
diset tpcc pg_count_ware $warehouses
diset tpcc pg_num_vu $tprocc_build_virtual_users

if {[info exists ::env(PG_TABLESPACE)] && $::env(PG_TABLESPACE) ne ""} {
    diset tpcc pg_tspace $::env(PG_TABLESPACE)
}

# Stored procedures must be chosen at build time: the driver script that runs
# later expects whichever form was built, so build and load must agree.
if {[info exists ::env(PG_STOREDPROCS)] && $::env(PG_STOREDPROCS) eq "true"} {
    diset tpcc pg_storedprocs true
    puts "  Stored procedures: enabled"
} else {
    diset tpcc pg_storedprocs false
    puts "  Stored procedures: disabled (prepared statements)"
}

if {[info exists ::env(PG_PARTITION)] && $::env(PG_PARTITION) eq "true"} {
    diset tpcc pg_partition true
}

if {[info exists ::env(PG_VACUUM)] && $::env(PG_VACUUM) eq "true"} {
    diset tpcc pg_vacuum true
}

loadscript

puts "Current TPROC-C configuration:"
print dict

puts "Starting TPROC-C schema build..."
buildschema

puts "TPROC-C SCHEMA BUILD COMPLETE"
