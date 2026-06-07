; features – macros and conditional compilation
%define OUT_PORT 0xFFFFFF04

%macro push_r0
    mv.l    R0, -(SP)
%endmacro

%macro pop_r0
    mv.l    (SP)+, R0
%endmacro

.code
.org 0x1000

start:
    mv.l    #0x42, R0
    push_r0
    pop_r0

    %ifdef DEBUG
    mv.b    R0, (OUT_PORT)
    %else
    mv.b    #0x58, R0
    mv.b    R0, (OUT_PORT)
    %endif

    die