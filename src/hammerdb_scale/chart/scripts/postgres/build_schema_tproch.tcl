#!/bin/tclsh
# Build the TPROC-H schema on PostgreSQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set pg_port $::env(PG_PORT)

set tproch_user $::env(TPROCH_USER)
set tproch_password $::env(TPROCH_PASSWORD)
set tproch_database_name $::env(TPROCH_DATABASE_NAME)
set scale_factor $::env(TPROCH_SCALE_FACTOR)
set build_threads $::env(TPROCH_BUILD_THREADS)

foreach var {USERNAME PASSWORD HOST PG_PORT TPROCH_DATABASE_NAME TPROCH_SCALE_FACTOR} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-H SCHEMA BUILD FOR POSTGRESQL"
puts "  Host: $host:$pg_port"
puts "  Database: $tproch_database_name"
puts "  Scale Factor: $scale_factor"
puts "  Build Threads: $build_threads"

dbset db pg
dbset bm TPC-H

diset connection pg_host $host
diset connection pg_port $pg_port
if {[info exists ::env(PG_SSLMODE)]} {
    diset connection pg_sslmode $::env(PG_SSLMODE)
}

diset tpch pg_tpch_superuser $username
diset tpch pg_tpch_superuserpass $password
diset tpch pg_tpch_defaultdbase postgres

diset tpch pg_tpch_user $tproch_user
diset tpch pg_tpch_pass $tproch_password
diset tpch pg_tpch_dbase $tproch_database_name
diset tpch pg_scale_fact $scale_factor
diset tpch pg_num_tpch_threads $build_threads

if {[info exists ::env(PG_TABLESPACE)] && $::env(PG_TABLESPACE) ne ""} {
    diset tpch pg_tpch_tspace $::env(PG_TABLESPACE)
}

loadscript

puts "Current TPROC-H configuration:"
print dict

puts "Starting TPROC-H schema build..."
buildschema

puts "TPROC-H SCHEMA BUILD COMPLETE"
