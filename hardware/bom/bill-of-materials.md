# Robot Bill of Materials

This inventory consolidates component and supplier links discussed in the direct-message thread with Thomas Vernay. Quantities reflect the latest explicit quantity found in that thread; they are purchasing quantities and may include spares. Links to papers, internal systems, job postings, and Slack messages are intentionally excluded.

## Main Robot

| Subsystem | Component | Part / option | Qty. | Supplier | Status / note |
|---|---|---:|---:|---|---|
| Sample handling | 24-deep-well plate | OptiWell 24-well deep-well plate | TBD | [MTC Bio](https://mtcbiotech.com/product/24-well-plates/) | Selected sample format |
| LAF enclosure | Laminar-flow cabinet | B0CN2HXRSL | 1 | [Amazon](https://www.amazon.de/dp/B0CN2HXRSL) | Selected from the compared cabinet options |
| Frame | V-slot aluminium profile | 20 x 20 mm, 750 mm | 1 | [MakerSupplies](https://makersupplies.dk/v-slot-profil-20x20-sort/) | Discussed replacement for an MGN rail |
| Frame | V-slot gantry plate | 20 mm system | 1 | [MakerSupplies](https://makersupplies.dk/v-slot-gantry-plade-20mm/) | Used with V-slot profile |
| Frame | Solid V-wheel kit | V-slot wheel kit | 4 | [MakerSupplies](https://makersupplies.dk/solid-v-wheel-kit/) | Used with V-slot profile |
| Linear motion | Lead screw and nut | T8, 8 x 800 mm, bronze nut | 2 | [Gleanntronics](https://www.gleanntronics.ie/product/t8-lead-screw-8mm-x-800mm-with-brass-nut/) | Double-Z drive |
| Linear motion | Lead screw and nut | T8, 8 x 600 mm, bronze nut | 4 | [Gleanntronics](https://www.gleanntronics.ie/product/t8-lead-screw-8mm-x-600mm-with-brass-nut/) | Earlier purchase list; verify installed lengths |
| Linear motion | GT2 timing belt | 10 mm wide, 5 m | 2 | [3D Eksperten](https://3deksperten.dk/products/2gt-timing-belt-w10mm-l5000mm) | Gantry transmission |
| Linear motion | Flexible shaft coupling | 5 x 8 mm | 2 | [3D Eksperten](https://3deksperten.dk/products/flexible-coupling-5x8mm) | Z-axis coupling |
| Linear motion | GT2 pulley | 20-tooth, 5 mm bore, 6 mm belt | 1 | [Amazon](https://www.amazon.de/dp/B0CWLHGPFV) | Latest pulley list |
| Linear motion | Timing pulley | Option 20-80T-8B-6 | 3 | [Amazon](https://www.amazon.de/dp/B0CQQZ4ZRR) | Exact option specified in DM |
| Linear motion | Ball bearings | 8 mm shielded miniature bearings | 2 packs | [Amazon](https://www.amazon.de/dp/B0FPGDCN8Z) | Verify bearing dimensions and pack count |
| Motion | NEMA 17 stepper motor | 2.5 A, 48 mm | 6 | [3D Eksperten](https://3deksperten.dk/products/nema17-stepper-motor-2-5a-48mm) | Four in first list and two in later list |
| Motion | High-torque stepper motor | SANMOTION SM2564C40B41, 24 V, 4 A, 2.5 Nm | 1 | [Mouser](https://www.mouser.dk/ProductDetail/SANMOTION/SM2564C40B41) | Confirmed ordered by Thomas |
| Motion control | Stepper driver | MKS TB67S109 with heatsink | 12+ | [3D Eksperten](https://3deksperten.dk/products/mks-tb67s109-stepper-driver-incl-big-heatsink-1) | Repeated orders; final installed/spare count must be reconciled |
| Motion control | Stepper driver | DRV8825 | 1 | [ArduinoTech](https://arduinotech.dk/shop/drv8825-stepper-motor-driver/) | Earlier pump prototype |
| Motion control | LED/actuator driver | DFRobot DRI0043 | 2 | [Mouser](https://www.mouser.dk/ProductDetail/DFRobot/DRI0043) | Verify final use |
| Control | Single-board computer | Raspberry Pi SC1111 | 1 | [Mouser](https://www.mouser.dk/ProductDetail/Raspberry-Pi/SC1111) | Earlier Pi order |
| Control | Single-board computer | Raspberry Pi SC1157 | 1 | [Mouser](https://www.mouser.dk/ProductDetail/Raspberry-Pi/SC1157) | Later Pi order; verify installed SKU |
| Control | Microcontroller board | ESP32-DevKitC-32E | 4 | [Mouser](https://www.mouser.dk/ProductDetail/Espressif-Systems/ESP32-DevKitC-32E) | Two listed in each of two orders |
| Control | STM32 development board | NUCLEO-G474RE | 1 | [Mouser](https://www.mouser.dk/ProductDetail/STMicroelectronics/NUCLEO-G474RE) | OD prototype |
| Power | 24 V power supply | Mean Well LRS-350N2-24 | 1 | [Mouser](https://www.mouser.dk/ProductDetail/MEAN-WELL/LRS-350N2-24) | Main 24 V supply |
| Safety / homing | Limit switch | Omron SS-5GL2 | 10 | [Mouser](https://www.mouser.dk/ProductDetail/Omron-Electronics/SS-5GL2) | Gantry and Z-axis limits |
| Wiring | Six-pin cable assembly | CABLE-PH06 | 12 | [DigiKey](https://www.digikey.dk/da/products/detail/analog-devices-inc-maxim-integrated/CABLE-PH06/9381902) | Order confirmed; quantity increased from 10 to 12 |
| Wiring | Ribbon cable | 10-pin jumper ribbon, 1.27/2.54 mm | 2 | [Amazon](https://www.amazon.de/dp/B09R42ZGQD) | Wiring harness material |
| Wiring | Micro-USB cable | USB-A to Micro-B, at least 2.5 m | 1 | [Amazon](https://www.amazon.de/dp/B0CSYKLKL2) | Verify purchased length |
| Wiring | Ribbon cable | 3M 8132-04-100 | 10 m | [DigiKey](https://www.digikey.dk/en/products/detail/3m/8132-04-100/1217834) | Verify conductor count |
| Thermal management | Heatsink | Assmann V2016B | 7 | [DigiKey](https://www.digikey.dk/en/products/detail/assmann-wsw-components/V2016B/3511426) | Driver cooling |
| Maintenance | Contact cleaner / lubricant | B0060K0VKI | 1 | [Amazon](https://www.amazon.de/dp/B0060K0VKI) | Anti-static, water-displacing spray |

## Seven-Syringe Pump

| Component | Part / option | Qty. | Supplier | Status / note |
|---|---:|---:|---|---|
| Long-stroke stepper actuator | 90 mm, 5 V | 1 | [ArduinoTech](https://arduinotech.dk/shop/precision-long-stroke-90mm-5v-stepper-motor/) | Early pump development |
| Disposable syringe | 0.3 mL | 1 pack | [Amazon](https://www.amazon.de/dp/B0CB9HCKWP) | Verify final syringe size |
| Check valve | Chemical-resistant membrane valve | 2 | [Amazon](https://www.amazon.de/dp/B0BS1DWB4Y) | Pump fluid path |
| Check valve | 4 mm inline valve | 2 | [Amazon](https://www.amazon.de/dp/B0FH62F5CY) | Pump fluid path |
| Hose connector set | Assorted barbed connectors | 1 | [Amazon](https://www.amazon.de/dp/B015EKYP7Y) | Pump plumbing |
| Irrigation hose coupling | VooGenzek 4 mm connector set | 1 pack | [Amazon](https://www.amazon.de/dp/B0CW36CB9L) | Latest pump list superseded the earlier quantity of two |
| Silicone tube | Transparent flexible transfer tube | 1 | [Amazon](https://www.amazon.de/dp/B0GJLD4PR7) | Pump plumbing |
| Flow distributor | Six-outlet adjustable air divider | 4 | [Amazon](https://www.amazon.de/dp/B08CKMSH6G) | Pump manifold candidate/order |
| Flow distributor | Six-way plastic divider | 3 | [Amazon](https://www.amazon.de/dp/B0BWMKZRWR) | Pump manifold candidate/order |
| Flow splitter | Aquarium hose splitter | 2 | [Amazon](https://www.amazon.de/dp/B0BTDJ4BQ8) | Pump manifold candidate/order |
| Unidentified pump item | B0CGNL26YZ | 1 | [Amazon](https://www.amazon.de/dp/B0CGNL26YZ) | Product title was not present in Slack export; verify |

## Tool Interface and Dispensing

| Component | Part / option | Qty. | Supplier | Status / note |
|---|---:|---:|---|---|
| Magnetic pogo connector | B0CVZWLNM2 | TBD | [Amazon](https://www.amazon.de/dp/B0CVZWLNM2) | Tool-connector candidate |
| Eight-pin magnetic pogo connector | B0D1KSC2V8 | TBD | [Amazon](https://www.amazon.de/dp/B0D1KSC2V8) | Tool-connector candidate |
| Magnetic pogo connector | Short-link item 03XizdiG | TBD | [Amazon](https://a.co/d/03XizdiG) | Later pogo option; verify exact model |
| Dosing needles | Assorted blunt needles | TBD | [Amazon](https://www.amazon.de/dp/B0DZ5M3WGZ) | Dispensing tool candidate |
| Curved dosing needle | 14 G blunt needle | TBD | [Amazon](https://www.amazon.de/dp/B0C4Y7828N) | Dispensing tool candidate |
| Servo | DFRobot SER0019 | 3 | [Mouser](https://www.mouser.dk/ProductDetail/DFRobot/SER0019) | Two in OD/electronics list and one later tool order |

## OD Prototypes

| Component | Part / option | Qty. | Supplier | Status / note |
|---|---:|---:|---|---|
| Photodiode | BPW34 / BPW-34-S | 50 | [Mouser](https://www.mouser.dk/ProductDetail/Vishay-Semiconductors/BPW34) | Ten in early prototype order and 40 in later order |
| Operational amplifier | LM358AM/NOPB | 10 | [Mouser](https://www.mouser.dk/ProductDetail/Texas-Instruments/LM358AM-NOPB) | First prototype |
| Operational amplifier | LM358N | 3 | [Mouser](https://www.mouser.dk/ProductDetail/Texas-Instruments/LM358N) | Early prototype order |
| Operational amplifier | MCP6002-I/P | 15 | [Mouser](https://www.mouser.dk/ProductDetail/Microchip-Technology/MCP6002-I-P) | Second prototype |
| Red LED | Broadcom HLMP-EG08-WZ000 | 30 | [Mouser](https://www.mouser.dk/ProductDetail/Broadcom-Avago/HLMP-EG08-WZ000) | Second prototype |
| LED driver | DFRobot SEN0527, TLC59711-based | 8 | [Mouser](https://www.mouser.dk/ProductDetail/DFRobot/SEN0527) | Six in early list plus two later boards |
| Ceramic capacitor | Vishay K104K15X7RF5WH5, 0.1 uF | 60 | [Mouser](https://www.mouser.dk/ProductDetail/Vishay-BC-Components/K104K15X7RF5WH5) | Amplifier filtering |
| Resistor | Stackpole RNF14FTD1M00, 1 Mohm | 45 | [Mouser](https://www.mouser.dk/ProductDetail/Stackpole-Electronics/RNF14FTD1M00) | Thirty in OD order and 15 later |
| Proto board / accessory | Adafruit 1455 | 2 | [Mouser](https://www.mouser.dk/ProductDetail/Adafruit/1455) | Verify function in final prototype |
| Prototype component | Soldered 000035 | 5 | [Soldered](https://soldered.com/product/000035/) | Verify description before publication |
| Enclosure | Hammond CSG12124 | 1 | [Mouser](https://www.mouser.dk/ProductDetail/Hammond-Manufacturing/CSG12124) | Electronics enclosure |

## Alternatives, Replacements, and Unresolved Items

These links were part of design or purchasing discussions but should not be presented as installed parts without checking the assembled robot.

| Component / discussion | Link | Status / note |
|---|---|---|
| Alternative laminar-flow cabinet | [Amazon B0FG2PKVLR](https://www.amazon.de/dp/B0FG2PKVLR) | Compared, not selected |
| Alternative laminar-flow cabinet | [Amazon B0F87KBT4R](https://www.amazon.de/dp/B0F87KBT4R) | Compared, not selected |
| MGN7C 600 mm rail | [Amazon B0C4P34WQL](https://www.amazon.de/dp/B0C4P34WQL) | Candidate before V-slot choice |
| Smooth pulley | [Amazon B097PSSXW2](https://www.amazon.de/dp/B097PSSXW2) | Candidate |
| MGN7H 750 mm rail | [Amazon B0GWPZTHYL](https://www.amazon.de/dp/B0GWPZTHYL) | Candidate |
| HGR20 800 mm rail set | [Amazon B0F9DPQTYD](https://www.amazon.de/dp/B0F9DPQTYD) | Candidate suggested by Thomas |
| MGN9H 750 mm rail | [Amazon B0BPH9H521](https://www.amazon.de/dp/B0BPH9H521) | Candidate suggested by Thomas |
| MGN7H 800 mm rail | [Amazon B0C4P1L4VC](https://www.amazon.de/dp/B0C4P1L4VC) | Candidate |
| Digital potentiometer | [ArduinoTech X9C103S](https://arduinotech.dk/shop/x9c103s-digital-potentiometer-module/) | Explicitly marked unnecessary for pump |
| JST-PH connector kit | [3D Eksperten](https://3deksperten.dk/products/jst-ph-connector-kit) | Unavailable when order was placed |
| Capacitor replacement | [Mouser 594-K104M10X7RF5UH5](https://www.mouser.dk/ProductDetail/Vishay-BC-Components/K104M10X7RF5UH5) | Substitute for unavailable K104M10X7RF5UL2; different lead spacing |
| Resistor replacement | [Mouser MBB02070C1503FC1](https://www.mouser.dk/ProductDetail/Vishay-BC-Components/MBB02070C1503FC1) | Substitute for unavailable MBB02070C1503FCT00 |
| Unidentified Amazon component | [B0CLRTJ3L2](https://www.amazon.de/dp/B0CLRTJ3L2) | Title absent from Slack export; verify |
| Unidentified Amazon component | [B0BDYQ2LP9](https://www.amazon.de/dp/B0BDYQ2LP9) | Title absent from Slack export; verify |
| Unidentified Amazon component | [B0BTY1D14C](https://www.amazon.de/dp/B0BTY1D14C) | Title absent from Slack export; verify |
| Unidentified Amazon component | [B0DSD9YF72](https://www.amazon.de/dp/B0DSD9YF72) | Quantity two in initial list; verify |
| Unidentified Amazon component | [B0BLS9P2S2](https://www.amazon.de/dp/B0BLS9P2S2) | Title absent from Slack export; verify |
| Unidentified Amazon component | [B096R4Q9Z3](https://www.amazon.de/dp/B096R4Q9Z3) | Title absent from Slack export; verify |
| Unidentified Amazon component | [B07H7FH8JX](https://www.amazon.de/dp/B07H7FH8JX) | Quantity three in July order; verify |
| Unidentified short-link component | [Amazon 0h570iG4](https://amzn.eu/d/0h570iG4) | Quantity two; verify before publication |

## Verification Notes

- Reconcile repeated order quantities against the installed robot and remaining spares, especially TB67S109 drivers, stepper motors, and OD components.
- Confirm which Raspberry Pi SKU is installed and retain only that row in the final public BOM.
- Resolve the unidentified Amazon items before treating this as a final manufacturing BOM.
- Supplier availability and prices change; manufacturer part numbers should remain the primary identifiers.
