# Emit TPROC-C results for the job recorded by load_test_tprocc.tcl.

proc getjobid {filename} {
    set fd [open $filename r]
    set jobid [lindex [split [gets $fd] =] 1]
    close $fd
    return $jobid
}

set tmpdir $::env(TMPDIR)
set ::outputfile $tmpdir/mysql_tprocc
set filename $::outputfile
set jobid [getjobid $filename]

if {$jobid eq ""} {
    puts "Job ID not found in the output file."
    exit 1
}

jobs format JSON

puts "TRANSACTION RESPONSE TIMES"
puts [job $jobid timing]

puts "TRANSACTION COUNT"
puts [jobs $jobid tcount]

puts "HAMMERDB RESULT"
puts [jobs $jobid result]
