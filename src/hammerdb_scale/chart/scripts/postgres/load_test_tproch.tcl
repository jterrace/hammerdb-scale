#!/bin/tclsh
# Run the TPROC-H query set against PostgreSQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set pg_port $::env(PG_PORT)

set tproch_user $::env(TPROCH_USER)
set tproch_password $::env(TPROCH_PASSWORD)
set tproch_database_name $::env(TPROCH_DATABASE_NAME)
set scale_factor $::env(TPROCH_SCALE_FACTOR)
set virtual_users $::env(TPROCH_VIRTUAL_USERS)
set total_querysets $::env(TPROCH_TOTAL_QUERYSETS)
set tmpdir $::env(TMPDIR)

foreach var {USERNAME PASSWORD HOST PG_PORT TPROCH_DATABASE_NAME TPROCH_VIRTUAL_USERS} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-H LOAD TEST FOR POSTGRESQL"
puts "  Host: $host:$pg_port"
puts "  Database: $tproch_database_name"
puts "  Scale Factor: $scale_factor"
puts "  Virtual Users: $virtual_users"
puts "  Query Sets: $total_querysets"

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
diset tpch pg_total_querysets $total_querysets

if {[info exists ::env(PG_MAX_PARALLEL_WORKERS)]} {
    diset tpch pg_degree_of_parallel $::env(PG_MAX_PARALLEL_WORKERS)
}

# TPROC-H writes per-query timings to the temp log, which the parse phase reads.
vuset logtotemp 1
loadscript

puts "STARTING TPROC-H VIRTUAL USERS"
vuset vu $virtual_users
vucreate
puts "TEST STARTED"

set jobid [ vurun ]
puts "vurun completed with job ID: $jobid"
vudestroy

puts "TPROC-H LOAD TEST COMPLETE"

puts "Creating output file at: $tmpdir/postgres_tproch"
set of [ open $tmpdir/postgres_tproch w ]
puts $of $jobid
close $of
puts "Job ID $jobid written to $tmpdir/postgres_tproch"
