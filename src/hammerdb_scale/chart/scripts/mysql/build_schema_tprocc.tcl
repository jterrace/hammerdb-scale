#!/bin/tclsh
# Build the TPROC-C schema on MySQL.

set username $::env(USERNAME)
set password $::env(PASSWORD)
set host $::env(HOST)
set mysql_port $::env(MYSQL_PORT)

set tprocc_user $::env(TPROCC_USER)
set tprocc_password $::env(TPROCC_PASSWORD)
set tprocc_database_name $::env(TPROCC_DATABASE_NAME)
set tprocc_build_virtual_users $::env(TPROCC_BUILD_VIRTUAL_USERS)
set warehouses $::env(WAREHOUSES)

foreach var {USERNAME PASSWORD HOST MYSQL_PORT TPROCC_DATABASE_NAME WAREHOUSES TPROCC_BUILD_VIRTUAL_USERS} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts "Error: Environment variable $var is not set or empty"
        exit 1
    }
}

puts "SETTING UP TPROC-C SCHEMA BUILD FOR MYSQL"
puts "  Host: $host:$mysql_port"
puts "  Database: $tprocc_database_name"
puts "  Warehouses: $warehouses"
puts "  Build Virtual Users: $tprocc_build_virtual_users"

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
diset tpcc mysql_count_ware $warehouses
diset tpcc mysql_num_vu $tprocc_build_virtual_users

if {[info exists ::env(MYSQL_STOREDPROCS)] && $::env(MYSQL_STOREDPROCS) eq "true"} {
    diset tpcc mysql_storedprocs true
    puts "  Stored procedures: enabled"
} else {
    diset tpcc mysql_storedprocs false
    puts "  Stored procedures: disabled (prepared statements)"
}

if {[info exists ::env(MYSQL_PARTITION)] && $::env(MYSQL_PARTITION) eq "true"} {
    diset tpcc mysql_partition true
}

loadscript

puts "Current TPROC-C configuration:"
print dict

puts "Starting TPROC-C schema build..."
buildschema

puts "TPROC-C SCHEMA BUILD COMPLETE"
