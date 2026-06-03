; hello_user_name – asks username, prints "Hello, <username>!"
%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.data
prompt:    pstr "What is your name?"
greeting:  pstr "Hello, "
name_buf:  dw 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0  ; 16 words for name
end_greet: pstr "!"

.code
.org 0x1000

start:
    ; Print greeting
    mv.l    #prompt, R0       ; set prompt pointer to R0
    jsr     print_string      ; goto procedure print_string

    mv.b    #0x0A, R0         ; add newline
    mv.b    R0, (OUT_PORT)

    ; Read name into name_buf
    mv.l    #name_buf, R1     ; buffer pointer
    mv.l    #0, R2            ; symbols counter

read_loop:
    mv.b    (IN_PORT), R0     ; load current symbol

    cmp.b   #0x0A, R0         ; compare current symbol with '\n'
    beq     read_done         ; if true then goto read_done

    cmp.b   #0, R0            ; compare current symbol with 0
    beq     read_done         ; if true then goto read_done

    mv.b    R0, (R1)+         ; save current symbol to buffer & increment buffer pointer

    add.l   #1, R2            ; increment counter
    cmp.l   #16, R2           ; compare counter with max size
    blt     read_loop         ; if there are space to read then goto read_loop

read_done:
    ; Print "Hello, "
    mv.l    R2, R4
    mv.l    #greeting, R0     ; set greeting pointer to R0
    jsr     print_string      ; goto procedure print_string

    ; Print name_buf (R2 symbols)
    mv.l    #name_buf, R1     ; buffer pointer
    mv.l    R4, R3            ; counter

name_print_loop:
    cmp.l   #0, R3            ; compare counter with 0
    beq     name_print_done   ; if true then goto name_print_done
    mv.b    (R1)+, R0         ; load current symbol from buffer
    mv.b    R0, (OUT_PORT)    ; print current symbol to output
    sub.l   #1, R3            ; decrement counter
    jmp     name_print_loop   ; goto name_print_loop

name_print_done:
    ; Print "!"
    mv.l    #end_greet, R0    ; set end_greet pointer to R0
    jsr     print_string      ; goto procedure print_string

    die                       ; stops program

; Procedure for printing pstr (address in R0)
print_string:
    mv.b    (R0)+, R1         ; load length of printing string
    mv.l    R1, R2            ; set length as counter

print_loop:
    cmp.b   #0, R2            ; compare counter with 0
    beq     print_done        ; if true then goto print_done
    mv.b    (R0)+, R1         ; symbol
    mv.b    R1, (OUT_PORT)    ; print current symbol to the output
    sub.b   #1, R2            ; decrement counter
    jmp     print_loop        ; goto print_loop

print_done:
    rts                       ; return to main program