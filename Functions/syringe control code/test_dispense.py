from pi_dispense import dispense

reply = dispense(
    port="/dev/ttyUSB0",   # change if needed
    calibration_file="calibration.json",
    A=150,
    B=25,
    C=0,
    D=100,
    E=0,
    F=10,
    G=75
)

print("ESP32 replied:", reply)
