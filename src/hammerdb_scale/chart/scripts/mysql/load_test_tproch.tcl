#!/bin/tclsh
# Run the TPROC-H query set against MySQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set mysql_port $::env(MYSQL_PORT)

set tproch_user $::env(TPROCH_USER)
set tproch_password $::env(TPROCH_PASSWORD)
set tproch_database_name $::env(TPROCH_DATABASE_NAME)
set scale_factor $::env(TPROCH_SCALE_FACTOR)
set virtual_users $::env(TPROCH_VIRTUAL_USERS)
set total_querysets $::env(TPROCH_TOTAL_QUERYSETS)
set tmpdir $::env(TMPDIR)

foreach var {USERNAME PASSWORD HOST MYSQL_PORT TPROCH_DATABASE_NAME TPROCH_VIRTUAL_USERS} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-H LOAD TEST FOR MYSQL"
puts "  Host: $host:$mysql_port"
puts "  Database: $tproch_database_name"
puts "  Scale Factor: $scale_factor"
puts "  Virtual Users: $virtual_users"
puts "  Query Sets: $total_querysets"

dbset db mysql
dbset bm TPC-H

diset connection mysql_host $host
diset connection mysql_port $mysql_port

if {[info exists ::env(MYSQL_SOCKET)] && $::env(MYSQL_SOCKET) ne ""} {
    diset connection mysql_socket $::env(MYSQL_SOCKET)
}

diset tpch mysql_tpch_user $username
diset tpch mysql_tpch_pass $password

diset tpch mysql_tpch_dbase $tproch_database_name
diset tpch mysql_scale_fact $scale_factor
diset tpch mysql_total_querysets $total_querysets

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

puts "Creating output file at: $tmpdir/mysql_tproch"
set of [ open $tmpdir/mysql_tproch w ]
puts $of $jobid
close $of
puts "Job ID $jobid written to $tmpdir/mysql_tproch"
