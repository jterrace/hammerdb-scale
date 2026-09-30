#!/bin/tclsh
# Run the TPROC-C workload against MySQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set mysql_port $::env(MYSQL_PORT)

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

foreach var {USERNAME PASSWORD HOST MYSQL_PORT VIRTUAL_USERS TPROCC_DATABASE_NAME} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-C LOAD TEST FOR MYSQL"
puts "  Host: $host:$mysql_port"
puts "  Database: $tprocc_database_name"
puts "  Virtual Users: $virtual_users"
puts "  Duration: $duration minutes"
puts "  Rampup: $rampup minutes"

dbset db mysql
dbset bm TPC-C

diset connection mysql_host $host
diset connection mysql_port $mysql_port

if {[info exists ::env(MYSQL_SOCKET)] && $::env(MYSQL_SOCKET) ne ""} {
    diset connection mysql_socket $::env(MYSQL_SOCKET)
}

diset tpcc mysql_user $username
diset tpcc mysql_pass $password

diset tpcc mysql_dbase $tprocc_database_name

diset tpcc mysql_driver timed
diset tpcc mysql_total_iterations $total_iterations
diset tpcc mysql_rampup $rampup
diset tpcc mysql_duration $duration

if {[info exists ::env(MYSQL_STOREDPROCS)] && $::env(MYSQL_STOREDPROCS) eq "true"} {
    diset tpcc mysql_storedprocs true
    puts "  Stored procedures: enabled"
} else {
    diset tpcc mysql_storedprocs false
    puts "  Stored procedures: disabled (prepared statements)"
}

if {[info exists ::env(TPROCC_ALLWAREHOUSE)] && $::env(TPROCC_ALLWAREHOUSE) eq "true"} {
    diset tpcc mysql_allwarehouse true
}

if {$tprocc_timeprofile eq "true"} {
    diset tpcc mysql_timeprofile true
}

diset tpcc mysql_keyandthink false

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

puts "Creating output file at: $tmpdir/mysql_tprocc"
set of [ open $tmpdir/mysql_tprocc w ]
puts $of $jobid
close $of
puts "Job ID $jobid written to $tmpdir/mysql_tprocc"
