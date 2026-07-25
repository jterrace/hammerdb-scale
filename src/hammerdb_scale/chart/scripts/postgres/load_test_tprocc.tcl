#!/bin/tclsh
# Run the TPROC-C workload against PostgreSQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set pg_port $::env(PG_PORT)

set virtual_users $::env(VIRTUAL_USERS)
set tprocc_user $::env(TPROCC_USER)
set tprocc_password $::env(TPROCC_PASSWORD)
set tprocc_database_name $::env(TPROCC_DATABASE_NAME)
set rampup $::env(RAMPUP)
set duration $::env(DURATION)
set total_iterations $::env(TOTAL_ITERATIONS)
set tmpdir $::env(TMPDIR)
set tprocc_log_to_temp $::env(TPROCC_LOG_TO_TEMP)
set tprocc_use_transaction_counter $::env(TPROCC_USE_TRANSACTION_COUNTER)
set tprocc_timeprofile $::env(TPROCC_TIMEPROFILE)

foreach var {USERNAME PASSWORD HOST PG_PORT VIRTUAL_USERS TPROCC_DATABASE_NAME} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-C LOAD TEST FOR POSTGRESQL"
puts "  Host: $host:$pg_port"
puts "  Database: $tprocc_database_name"
puts "  Virtual Users: $virtual_users"
puts "  Duration: $duration minutes"
puts "  Rampup: $rampup minutes"

dbset db pg
dbset bm TPC-C

diset connection pg_host $host
diset connection pg_port $pg_port
if {[info exists ::env(PG_SSLMODE)]} {
    diset connection pg_sslmode $::env(PG_SSLMODE)
}

diset tpcc pg_superuser $username
diset tpcc pg_superuserpass $password
diset tpcc pg_defaultdbase postgres

diset tpcc pg_user $tprocc_user
diset tpcc pg_pass $tprocc_password
diset tpcc pg_dbase $tprocc_database_name

diset tpcc pg_driver timed
diset tpcc pg_total_iterations $total_iterations
diset tpcc pg_rampup $rampup
diset tpcc pg_duration $duration

# Must match how the schema was built, or the driver calls procedures that
# do not exist.
if {[info exists ::env(PG_STOREDPROCS)] && $::env(PG_STOREDPROCS) eq "true"} {
    diset tpcc pg_storedprocs true
    puts "  Stored procedures: enabled"
} else {
    diset tpcc pg_storedprocs false
    puts "  Stored procedures: disabled (prepared statements)"
}

if {[info exists ::env(TPROCC_ALLWAREHOUSE)] && $::env(TPROCC_ALLWAREHOUSE) eq "true"} {
    diset tpcc pg_allwarehouse true
}

if {$tprocc_timeprofile eq "true"} {
    diset tpcc pg_timeprofile true
}

# Keying and thinking time off: this measures maximum throughput, not a
# simulated user population.
diset tpcc pg_keyandthink false

vuset logtotemp $tprocc_log_to_temp
loadscript

puts "STARTING TPROC-C VIRTUAL USERS"
vuset vu $virtual_users
vucreate
puts "TEST STARTED"

if {$tprocc_use_transaction_counter eq "true"} {
    puts "Starting transaction counter..."
    tcstart
    tcstatus
}

puts "About to run vurun command..."
set jobid [ vurun ]
puts "vurun completed with job ID: $jobid"
vudestroy

if {$tprocc_use_transaction_counter eq "true"} {
    puts "Stopping transaction counter..."
    tcstop
}

puts "Virtual users destroyed"
puts "TPROC-C LOAD TEST COMPLETE"

puts "Creating output file at: $tmpdir/postgres_tprocc"
set of [ open $tmpdir/postgres_tprocc w ]
puts $of $jobid
close $of
puts "Job ID $jobid written to $tmpdir/postgres_tprocc"
