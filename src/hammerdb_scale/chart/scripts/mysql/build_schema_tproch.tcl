#!/bin/tclsh
# Build the TPROC-H schema on MySQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set mysql_port $::env(MYSQL_PORT)

set tproch_user $::env(TPROCH_USER)
set tproch_password $::env(TPROCH_PASSWORD)
set tproch_database_name $::env(TPROCH_DATABASE_NAME)
set scale_factor $::env(TPROCH_SCALE_FACTOR)
set build_threads $::env(TPROCH_BUILD_THREADS)

foreach var {USERNAME PASSWORD HOST MYSQL_PORT TPROCH_DATABASE_NAME TPROCH_SCALE_FACTOR} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-H SCHEMA BUILD FOR MYSQL"
puts "  Host: $host:$mysql_port"
puts "  Database: $tproch_database_name"
puts "  Scale Factor: $scale_factor"
puts "  Build Threads: $build_threads"

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
diset tpch mysql_num_tpch_threads $build_threads

loadscript

puts "Current TPROC-H configuration:"
print dict

puts "Starting TPROC-H schema build..."
buildschema

puts "TPROC-H SCHEMA BUILD COMPLETE"
