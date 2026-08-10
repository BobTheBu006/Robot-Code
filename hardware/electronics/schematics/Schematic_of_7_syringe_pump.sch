<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE eagle SYSTEM "eagle.dtd">
<eagle version="9.7.0">
<drawing>
<settings>
<setting alwaysvectorfont="no"/>
<setting verticaltext="up"/>
</settings>
<grid distance="0.1" unitdist="inch" unit="inch" style="lines" multiple="1" display="no" altdistance="0.01" altunitdist="inch" altunit="inch"/>
<layers>
<layer number="1" name="Top" color="4" fill="1" visible="no" active="no"/>
<layer number="2" name="Route2" color="16" fill="3" visible="no" active="no"/>
<layer number="3" name="Route3" color="17" fill="1" visible="no" active="no"/>
<layer number="4" name="Route4" color="18" fill="1" visible="no" active="no"/>
<layer number="5" name="Route5" color="19" fill="1" visible="no" active="no"/>
<layer number="6" name="Route6" color="25" fill="1" visible="no" active="no"/>
<layer number="7" name="Route7" color="26" fill="1" visible="no" active="no"/>
<layer number="8" name="Route8" color="27" fill="1" visible="no" active="no"/>
<layer number="9" name="Route9" color="28" fill="1" visible="no" active="no"/>
<layer number="10" name="Route10" color="29" fill="1" visible="no" active="no"/>
<layer number="11" name="Route11" color="30" fill="1" visible="no" active="no"/>
<layer number="12" name="Route12" color="20" fill="1" visible="no" active="no"/>
<layer number="13" name="Route13" color="21" fill="1" visible="no" active="no"/>
<layer number="14" name="Route14" color="22" fill="1" visible="no" active="no"/>
<layer number="15" name="Route15" color="23" fill="1" visible="no" active="no"/>
<layer number="16" name="Bottom" color="1" fill="1" visible="no" active="no"/>
<layer number="17" name="Pads" color="2" fill="1" visible="no" active="no"/>
<layer number="18" name="Vias" color="2" fill="1" visible="no" active="no"/>
<layer number="19" name="Unrouted" color="6" fill="1" visible="no" active="no"/>
<layer number="20" name="Dimension" color="24" fill="1" visible="no" active="no"/>
<layer number="21" name="tPlace" color="7" fill="1" visible="no" active="no"/>
<layer number="22" name="bPlace" color="7" fill="1" visible="no" active="no"/>
<layer number="23" name="tOrigins" color="15" fill="1" visible="no" active="no"/>
<layer number="24" name="bOrigins" color="15" fill="1" visible="no" active="no"/>
<layer number="25" name="tNames" color="7" fill="1" visible="no" active="no"/>
<layer number="26" name="bNames" color="7" fill="1" visible="no" active="no"/>
<layer number="27" name="tValues" color="7" fill="1" visible="no" active="no"/>
<layer number="28" name="bValues" color="7" fill="1" visible="no" active="no"/>
<layer number="29" name="tStop" color="7" fill="3" visible="no" active="no"/>
<layer number="30" name="bStop" color="7" fill="6" visible="no" active="no"/>
<layer number="31" name="tCream" color="7" fill="4" visible="no" active="no"/>
<layer number="32" name="bCream" color="7" fill="5" visible="no" active="no"/>
<layer number="33" name="tFinish" color="6" fill="3" visible="no" active="no"/>
<layer number="34" name="bFinish" color="6" fill="6" visible="no" active="no"/>
<layer number="35" name="tGlue" color="7" fill="4" visible="no" active="no"/>
<layer number="36" name="bGlue" color="7" fill="5" visible="no" active="no"/>
<layer number="37" name="tTest" color="7" fill="1" visible="no" active="no"/>
<layer number="38" name="bTest" color="7" fill="1" visible="no" active="no"/>
<layer number="39" name="tKeepout" color="4" fill="11" visible="no" active="no"/>
<layer number="40" name="bKeepout" color="1" fill="11" visible="no" active="no"/>
<layer number="41" name="tRestrict" color="4" fill="10" visible="no" active="no"/>
<layer number="42" name="bRestrict" color="1" fill="10" visible="no" active="no"/>
<layer number="43" name="vRestrict" color="2" fill="10" visible="no" active="no"/>
<layer number="44" name="Drills" color="7" fill="1" visible="no" active="no"/>
<layer number="45" name="Holes" color="7" fill="1" visible="no" active="no"/>
<layer number="46" name="Milling" color="3" fill="1" visible="no" active="no"/>
<layer number="47" name="Measures" color="7" fill="1" visible="no" active="no"/>
<layer number="48" name="Document" color="7" fill="1" visible="no" active="no"/>
<layer number="49" name="Reference" color="7" fill="1" visible="no" active="no"/>
<layer number="51" name="tDocu" color="7" fill="1" visible="no" active="no"/>
<layer number="52" name="bDocu" color="7" fill="1" visible="no" active="no"/>
<layer number="88" name="SimResults" color="9" fill="1" visible="yes" active="yes"/>
<layer number="89" name="SimProbes" color="9" fill="1" visible="yes" active="yes"/>
<layer number="90" name="Modules" color="5" fill="1" visible="yes" active="yes"/>
<layer number="91" name="Nets" color="2" fill="1" visible="yes" active="yes"/>
<layer number="92" name="Busses" color="1" fill="1" visible="yes" active="yes"/>
<layer number="93" name="Pins" color="2" fill="1" visible="no" active="yes"/>
<layer number="94" name="Symbols" color="4" fill="1" visible="yes" active="yes"/>
<layer number="95" name="Names" color="7" fill="1" visible="yes" active="yes"/>
<layer number="96" name="Values" color="7" fill="1" visible="yes" active="yes"/>
<layer number="97" name="Info" color="7" fill="1" visible="yes" active="yes"/>
<layer number="98" name="Guide" color="6" fill="1" visible="yes" active="yes"/>
<layer number="255" name="Undefined" color="7" fill="1" visible="yes" active="yes"/>
</layers>
<schematic xreflabel="%F%N/%S.%C%R" xrefpart="/%S.%C%R">
<libraries>
<library name="Connector" urn="urn:adsk.eagle:library:16378166">
<description>Pin Headers |Terminal blocks | D-Sub | Backplane | FFC/FPC | Socket</description>
<packages>
<package name="1X02" urn="urn:adsk.eagle:footprint:47493538/12" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-1.27" y="0" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="1.27" y="0" drill="1.016" shape="octagon"/>
<wire x1="-1.905" y1="1.27" x2="-0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="1.27" x2="0" y2="0.635" width="0.1" layer="51"/>
<wire x1="0" y1="0.635" x2="0" y2="-0.635" width="0.1" layer="51"/>
<wire x1="0" y1="-0.635" x2="-0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="0.635" x2="-2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-1.905" y1="1.27" x2="-2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-0.635" x2="-1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="-1.27" x2="-1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0" y1="0.635" x2="0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="0.635" y1="1.27" x2="1.905" y2="1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="1.27" x2="2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="0.635" x2="2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="-0.635" x2="1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="-1.27" x2="0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0.635" y1="-1.27" x2="0" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-2.64" y1="1.37" x2="2.64" y2="1.37" width="0.2" layer="21"/>
<wire x1="2.64" y1="1.37" x2="2.64" y2="-1.37" width="0.2" layer="21"/>
<wire x1="2.64" y1="-1.37" x2="-2.64" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-2.64" y1="-1.37" x2="-2.64" y2="1.37" width="0.2" layer="21"/>
<rectangle x1="-1.524" y1="-0.254" x2="-1.016" y2="0.254" layer="51"/>
<rectangle x1="1.016" y1="-0.254" x2="1.524" y2="0.254" layer="51"/>
<text x="0" y="2.54" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-2.54" size="1.27" layer="27" align="center">&gt;VALUE</text>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-2.7638" y="-1.4938"/>
<vertex x="2.7638" y="-1.4938"/>
<vertex x="2.7638" y="1.4938"/>
<vertex x="-2.7638" y="1.4938"/>
</polygon>
</package>
<package name="1X02_90" urn="urn:adsk.eagle:footprint:47493536/12" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-1.27" y="-2.77" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="1.27" y="-2.77" drill="1.016" shape="octagon"/>
<text x="0" y="8.89" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-5.08" size="1.27" layer="27" align="center">&gt;VALUE</text>
<wire x1="-2.54" y1="-1.27" x2="-2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-1.27" x2="0" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0" y1="-1.27" x2="0" y2="1.27" width="0.1" layer="51"/>
<wire x1="0" y1="1.27" x2="-2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="0" y1="-1.27" x2="2.54" y2="-1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="-1.27" x2="2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="1.27" x2="0" y2="1.27" width="0.1" layer="51"/>
<wire x1="-2.64" y1="1.37" x2="2.64" y2="1.37" width="0.2" layer="21"/>
<wire x1="2.64" y1="1.37" x2="2.64" y2="-1.37" width="0.2" layer="21"/>
<wire x1="2.64" y1="-1.37" x2="-2.64" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-2.64" y1="-1.37" x2="-2.64" y2="1.37" width="0.2" layer="21"/>
<wire x1="-1.59" y1="7.27" x2="-0.95" y2="7.27" width="0.127" layer="51"/>
<wire x1="-0.95" y1="7.27" x2="-0.95" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-0.95" y1="-3.09" x2="-1.59" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-1.59" y1="-3.09" x2="-1.59" y2="7.27" width="0.127" layer="51"/>
<wire x1="0.95" y1="7.27" x2="1.59" y2="7.27" width="0.127" layer="51"/>
<wire x1="1.59" y1="7.27" x2="1.59" y2="-3.09" width="0.127" layer="51"/>
<wire x1="1.59" y1="-3.09" x2="0.95" y2="-3.09" width="0.127" layer="51"/>
<wire x1="0.95" y1="-3.09" x2="0.95" y2="7.27" width="0.127" layer="51"/>
<rectangle x1="-1.59" y1="-3.09" x2="-0.95" y2="7.27" layer="51"/>
<rectangle x1="0.95" y1="-3.09" x2="1.59" y2="7.27" layer="51"/>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-2.7638" y="-3.8238"/>
<vertex x="2.7638" y="-3.8238"/>
<vertex x="2.7638" y="7.5238"/>
<vertex x="-2.7638" y="7.5238"/>
</polygon>
</package>
<package name="1X07" urn="urn:adsk.eagle:footprint:47493516/11" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-7.62" y="0" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="-5.08" y="0" drill="1.016" shape="octagon"/>
<pad name="3" x="-2.54" y="0" drill="1.016" shape="octagon"/>
<pad name="4" x="0" y="0" drill="1.016" shape="octagon"/>
<pad name="5" x="2.54" y="0" drill="1.016" shape="octagon"/>
<pad name="6" x="5.08" y="0" drill="1.016" shape="octagon"/>
<pad name="7" x="7.62" y="0" drill="1.016" shape="octagon"/>
<wire x1="4.445" y1="1.27" x2="5.715" y2="1.27" width="0.1" layer="51"/>
<wire x1="5.715" y1="1.27" x2="6.35" y2="0.635" width="0.1" layer="51"/>
<wire x1="6.35" y1="0.635" x2="6.35" y2="-0.635" width="0.1" layer="51"/>
<wire x1="6.35" y1="-0.635" x2="5.715" y2="-1.27" width="0.1" layer="51"/>
<wire x1="1.27" y1="0.635" x2="1.905" y2="1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="1.27" x2="3.175" y2="1.27" width="0.1" layer="51"/>
<wire x1="3.175" y1="1.27" x2="3.81" y2="0.635" width="0.1" layer="51"/>
<wire x1="3.81" y1="0.635" x2="3.81" y2="-0.635" width="0.1" layer="51"/>
<wire x1="3.81" y1="-0.635" x2="3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="3.175" y1="-1.27" x2="1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="-1.27" x2="1.27" y2="-0.635" width="0.1" layer="51"/>
<wire x1="4.445" y1="1.27" x2="3.81" y2="0.635" width="0.1" layer="51"/>
<wire x1="3.81" y1="-0.635" x2="4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="5.715" y1="-1.27" x2="4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-3.175" y1="1.27" x2="-1.905" y2="1.27" width="0.1" layer="51"/>
<wire x1="-1.905" y1="1.27" x2="-1.27" y2="0.635" width="0.1" layer="51"/>
<wire x1="-1.27" y1="0.635" x2="-1.27" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-1.27" y1="-0.635" x2="-1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-1.27" y1="0.635" x2="-0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="1.27" x2="0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="0.635" y1="1.27" x2="1.27" y2="0.635" width="0.1" layer="51"/>
<wire x1="1.27" y1="0.635" x2="1.27" y2="-0.635" width="0.1" layer="51"/>
<wire x1="1.27" y1="-0.635" x2="0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0.635" y1="-1.27" x2="-0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="-1.27" x2="-1.27" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-6.35" y1="0.635" x2="-5.715" y2="1.27" width="0.1" layer="51"/>
<wire x1="-5.715" y1="1.27" x2="-4.445" y2="1.27" width="0.1" layer="51"/>
<wire x1="-4.445" y1="1.27" x2="-3.81" y2="0.635" width="0.1" layer="51"/>
<wire x1="-3.81" y1="0.635" x2="-3.81" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-3.81" y1="-0.635" x2="-4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-4.445" y1="-1.27" x2="-5.715" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-5.715" y1="-1.27" x2="-6.35" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-3.175" y1="1.27" x2="-3.81" y2="0.635" width="0.1" layer="51"/>
<wire x1="-3.81" y1="-0.635" x2="-3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-1.905" y1="-1.27" x2="-3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-8.89" y1="0.635" x2="-8.89" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-8.89" y1="0.635" x2="-8.255" y2="1.27" width="0.1" layer="51"/>
<wire x1="-8.255" y1="1.27" x2="-6.985" y2="1.27" width="0.1" layer="51"/>
<wire x1="-6.985" y1="1.27" x2="-6.35" y2="0.635" width="0.1" layer="51"/>
<wire x1="-6.35" y1="0.635" x2="-6.35" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-6.35" y1="-0.635" x2="-6.985" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-6.985" y1="-1.27" x2="-8.255" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-8.255" y1="-1.27" x2="-8.89" y2="-0.635" width="0.1" layer="51"/>
<wire x1="6.35" y1="0.635" x2="6.985" y2="1.27" width="0.1" layer="51"/>
<wire x1="6.985" y1="1.27" x2="8.255" y2="1.27" width="0.1" layer="51"/>
<wire x1="8.255" y1="1.27" x2="8.89" y2="0.635" width="0.1" layer="51"/>
<wire x1="8.89" y1="0.635" x2="8.89" y2="-0.635" width="0.1" layer="51"/>
<wire x1="8.89" y1="-0.635" x2="8.255" y2="-1.27" width="0.1" layer="51"/>
<wire x1="8.255" y1="-1.27" x2="6.985" y2="-1.27" width="0.1" layer="51"/>
<wire x1="6.985" y1="-1.27" x2="6.35" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-8.99" y1="1.37" x2="8.99" y2="1.37" width="0.2" layer="21"/>
<wire x1="8.99" y1="1.37" x2="8.99" y2="-1.37" width="0.2" layer="21"/>
<wire x1="8.99" y1="-1.37" x2="-8.99" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-8.99" y1="-1.37" x2="-8.99" y2="1.37" width="0.2" layer="21"/>
<rectangle x1="4.826" y1="-0.254" x2="5.334" y2="0.254" layer="51"/>
<rectangle x1="2.286" y1="-0.254" x2="2.794" y2="0.254" layer="51"/>
<rectangle x1="-0.254" y1="-0.254" x2="0.254" y2="0.254" layer="51"/>
<rectangle x1="-2.794" y1="-0.254" x2="-2.286" y2="0.254" layer="51"/>
<rectangle x1="-5.334" y1="-0.254" x2="-4.826" y2="0.254" layer="51"/>
<rectangle x1="-7.874" y1="-0.254" x2="-7.366" y2="0.254" layer="51"/>
<rectangle x1="7.366" y1="-0.254" x2="7.874" y2="0.254" layer="51"/>
<text x="0" y="2.54" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-2.54" size="1.27" layer="27" align="center">&gt;VALUE</text>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-9.1138" y="-1.4938"/>
<vertex x="9.1138" y="-1.4938"/>
<vertex x="9.1138" y="1.4938"/>
<vertex x="-9.1138" y="1.4938"/>
</polygon>
</package>
<package name="1X07_90" urn="urn:adsk.eagle:footprint:47493514/11" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-7.62" y="-2.77" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="-5.08" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="3" x="-2.54" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="4" x="0" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="5" x="2.54" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="6" x="5.08" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="7" x="7.62" y="-2.77" drill="1.016" shape="octagon"/>
<text x="0" y="8.89" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-5.08" size="1.27" layer="27" align="center">&gt;VALUE</text>
<wire x1="-8.89" y1="-1.27" x2="-8.89" y2="1.27" width="0.1" layer="51"/>
<wire x1="-8.89" y1="-1.27" x2="-6.35" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-6.35" y1="-1.27" x2="-6.35" y2="1.27" width="0.1" layer="51"/>
<wire x1="-6.35" y1="1.27" x2="-8.89" y2="1.27" width="0.1" layer="51"/>
<wire x1="-6.35" y1="-1.27" x2="-3.81" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-3.81" y1="-1.27" x2="-3.81" y2="1.27" width="0.1" layer="51"/>
<wire x1="-3.81" y1="1.27" x2="-6.35" y2="1.27" width="0.1" layer="51"/>
<wire x1="-3.81" y1="-1.27" x2="-1.27" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-1.27" y1="-1.27" x2="-1.27" y2="1.27" width="0.1" layer="51"/>
<wire x1="-1.27" y1="1.27" x2="-3.81" y2="1.27" width="0.1" layer="51"/>
<wire x1="-1.27" y1="-1.27" x2="1.27" y2="-1.27" width="0.1" layer="51"/>
<wire x1="1.27" y1="-1.27" x2="1.27" y2="1.27" width="0.1" layer="51"/>
<wire x1="1.27" y1="1.27" x2="-1.27" y2="1.27" width="0.1" layer="51"/>
<wire x1="1.27" y1="-1.27" x2="3.81" y2="-1.27" width="0.1" layer="51"/>
<wire x1="3.81" y1="-1.27" x2="3.81" y2="1.27" width="0.1" layer="51"/>
<wire x1="3.81" y1="1.27" x2="1.27" y2="1.27" width="0.1" layer="51"/>
<wire x1="3.81" y1="-1.27" x2="6.35" y2="-1.27" width="0.1" layer="51"/>
<wire x1="6.35" y1="-1.27" x2="6.35" y2="1.27" width="0.1" layer="51"/>
<wire x1="6.35" y1="1.27" x2="3.81" y2="1.27" width="0.1" layer="51"/>
<wire x1="6.35" y1="-1.27" x2="8.89" y2="-1.27" width="0.1" layer="51"/>
<wire x1="8.89" y1="-1.27" x2="8.89" y2="1.27" width="0.1" layer="51"/>
<wire x1="8.89" y1="1.27" x2="6.35" y2="1.27" width="0.1" layer="51"/>
<wire x1="-8.99" y1="1.37" x2="8.99" y2="1.37" width="0.2" layer="21"/>
<wire x1="8.99" y1="1.37" x2="8.99" y2="-1.37" width="0.2" layer="21"/>
<wire x1="8.99" y1="-1.37" x2="-8.99" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-8.99" y1="-1.37" x2="-8.99" y2="1.37" width="0.2" layer="21"/>
<wire x1="-7.94" y1="7.27" x2="-7.3" y2="7.27" width="0.127" layer="51"/>
<wire x1="-7.3" y1="7.27" x2="-7.3" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-7.3" y1="-3.09" x2="-7.94" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-7.94" y1="-3.09" x2="-7.94" y2="7.27" width="0.127" layer="51"/>
<wire x1="-5.4" y1="7.27" x2="-4.76" y2="7.27" width="0.127" layer="51"/>
<wire x1="-4.76" y1="7.27" x2="-4.76" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-4.76" y1="-3.09" x2="-5.4" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-5.4" y1="-3.09" x2="-5.4" y2="7.27" width="0.127" layer="51"/>
<wire x1="-2.86" y1="7.27" x2="-2.22" y2="7.27" width="0.127" layer="51"/>
<wire x1="-2.22" y1="7.27" x2="-2.22" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-2.22" y1="-3.09" x2="-2.86" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-2.86" y1="-3.09" x2="-2.86" y2="7.27" width="0.127" layer="51"/>
<wire x1="-0.32" y1="7.27" x2="0.32" y2="7.27" width="0.127" layer="51"/>
<wire x1="0.32" y1="7.27" x2="0.32" y2="-3.09" width="0.127" layer="51"/>
<wire x1="0.32" y1="-3.09" x2="-0.32" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-0.32" y1="-3.09" x2="-0.32" y2="7.27" width="0.127" layer="51"/>
<wire x1="2.22" y1="7.27" x2="2.86" y2="7.27" width="0.127" layer="51"/>
<wire x1="2.86" y1="7.27" x2="2.86" y2="-3.09" width="0.127" layer="51"/>
<wire x1="2.86" y1="-3.09" x2="2.22" y2="-3.09" width="0.127" layer="51"/>
<wire x1="2.22" y1="-3.09" x2="2.22" y2="7.27" width="0.127" layer="51"/>
<wire x1="4.76" y1="7.27" x2="5.4" y2="7.27" width="0.127" layer="51"/>
<wire x1="5.4" y1="7.27" x2="5.4" y2="-3.09" width="0.127" layer="51"/>
<wire x1="5.4" y1="-3.09" x2="4.76" y2="-3.09" width="0.127" layer="51"/>
<wire x1="4.76" y1="-3.09" x2="4.76" y2="7.27" width="0.127" layer="51"/>
<wire x1="7.3" y1="7.27" x2="7.94" y2="7.27" width="0.127" layer="51"/>
<wire x1="7.94" y1="7.27" x2="7.94" y2="-3.09" width="0.127" layer="51"/>
<wire x1="7.94" y1="-3.09" x2="7.3" y2="-3.09" width="0.127" layer="51"/>
<wire x1="7.3" y1="-3.09" x2="7.3" y2="7.27" width="0.127" layer="51"/>
<rectangle x1="-7.94" y1="-3.09" x2="-7.3" y2="7.27" layer="51"/>
<rectangle x1="-5.4" y1="-3.09" x2="-4.76" y2="7.27" layer="51"/>
<rectangle x1="-2.86" y1="-3.09" x2="-2.22" y2="7.27" layer="51"/>
<rectangle x1="-0.32" y1="-3.09" x2="0.32" y2="7.27" layer="51"/>
<rectangle x1="2.22" y1="-3.09" x2="2.86" y2="7.27" layer="51"/>
<rectangle x1="4.76" y1="-3.09" x2="5.4" y2="7.27" layer="51"/>
<rectangle x1="7.3" y1="-3.09" x2="7.94" y2="7.27" layer="51"/>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-9.1138" y="-3.8238"/>
<vertex x="9.1138" y="-3.8238"/>
<vertex x="9.1138" y="7.5238"/>
<vertex x="-9.1138" y="7.5238"/>
</polygon>
</package>
<package name="1X08" urn="urn:adsk.eagle:footprint:47493511/11" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-8.89" y="0" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="-6.35" y="0" drill="1.016" shape="octagon"/>
<pad name="3" x="-3.81" y="0" drill="1.016" shape="octagon"/>
<pad name="4" x="-1.27" y="0" drill="1.016" shape="octagon" rot="R90"/>
<pad name="5" x="1.27" y="0" drill="1.016" shape="octagon"/>
<pad name="6" x="3.81" y="0" drill="1.016" shape="octagon"/>
<pad name="7" x="6.35" y="0" drill="1.016" shape="octagon"/>
<pad name="8" x="8.89" y="0" drill="1.016" shape="octagon"/>
<wire x1="5.715" y1="1.27" x2="6.985" y2="1.27" width="0.1" layer="51"/>
<wire x1="6.985" y1="1.27" x2="7.62" y2="0.635" width="0.1" layer="51"/>
<wire x1="7.62" y1="0.635" x2="7.62" y2="-0.635" width="0.1" layer="51"/>
<wire x1="7.62" y1="-0.635" x2="6.985" y2="-1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="0.635" x2="3.175" y2="1.27" width="0.1" layer="51"/>
<wire x1="3.175" y1="1.27" x2="4.445" y2="1.27" width="0.1" layer="51"/>
<wire x1="4.445" y1="1.27" x2="5.08" y2="0.635" width="0.1" layer="51"/>
<wire x1="5.08" y1="0.635" x2="5.08" y2="-0.635" width="0.1" layer="51"/>
<wire x1="5.08" y1="-0.635" x2="4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="4.445" y1="-1.27" x2="3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="3.175" y1="-1.27" x2="2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="5.715" y1="1.27" x2="5.08" y2="0.635" width="0.1" layer="51"/>
<wire x1="5.08" y1="-0.635" x2="5.715" y2="-1.27" width="0.1" layer="51"/>
<wire x1="6.985" y1="-1.27" x2="5.715" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-1.905" y1="1.27" x2="-0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="1.27" x2="0" y2="0.635" width="0.1" layer="51"/>
<wire x1="0" y1="0.635" x2="0" y2="-0.635" width="0.1" layer="51"/>
<wire x1="0" y1="-0.635" x2="-0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0" y1="0.635" x2="0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="0.635" y1="1.27" x2="1.905" y2="1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="1.27" x2="2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="0.635" x2="2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="-0.635" x2="1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="-1.27" x2="0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0.635" y1="-1.27" x2="0" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-5.08" y1="0.635" x2="-4.445" y2="1.27" width="0.1" layer="51"/>
<wire x1="-4.445" y1="1.27" x2="-3.175" y2="1.27" width="0.1" layer="51"/>
<wire x1="-3.175" y1="1.27" x2="-2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="-2.54" y1="0.635" x2="-2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-0.635" x2="-3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-3.175" y1="-1.27" x2="-4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-4.445" y1="-1.27" x2="-5.08" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-1.905" y1="1.27" x2="-2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-0.635" x2="-1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="-1.27" x2="-1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-9.525" y1="1.27" x2="-8.255" y2="1.27" width="0.1" layer="51"/>
<wire x1="-8.255" y1="1.27" x2="-7.62" y2="0.635" width="0.1" layer="51"/>
<wire x1="-7.62" y1="0.635" x2="-7.62" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-7.62" y1="-0.635" x2="-8.255" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-7.62" y1="0.635" x2="-6.985" y2="1.27" width="0.1" layer="51"/>
<wire x1="-6.985" y1="1.27" x2="-5.715" y2="1.27" width="0.1" layer="51"/>
<wire x1="-5.715" y1="1.27" x2="-5.08" y2="0.635" width="0.1" layer="51"/>
<wire x1="-5.08" y1="0.635" x2="-5.08" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-5.08" y1="-0.635" x2="-5.715" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-5.715" y1="-1.27" x2="-6.985" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-6.985" y1="-1.27" x2="-7.62" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-10.16" y1="0.635" x2="-10.16" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-9.525" y1="1.27" x2="-10.16" y2="0.635" width="0.1" layer="51"/>
<wire x1="-10.16" y1="-0.635" x2="-9.525" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-8.255" y1="-1.27" x2="-9.525" y2="-1.27" width="0.1" layer="51"/>
<wire x1="7.62" y1="0.635" x2="8.255" y2="1.27" width="0.1" layer="51"/>
<wire x1="8.255" y1="1.27" x2="9.525" y2="1.27" width="0.1" layer="51"/>
<wire x1="9.525" y1="1.27" x2="10.16" y2="0.635" width="0.1" layer="51"/>
<wire x1="10.16" y1="0.635" x2="10.16" y2="-0.635" width="0.1" layer="51"/>
<wire x1="10.16" y1="-0.635" x2="9.525" y2="-1.27" width="0.1" layer="51"/>
<wire x1="9.525" y1="-1.27" x2="8.255" y2="-1.27" width="0.1" layer="51"/>
<wire x1="8.255" y1="-1.27" x2="7.62" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-10.26" y1="1.37" x2="10.26" y2="1.37" width="0.2" layer="21"/>
<wire x1="10.26" y1="1.37" x2="10.26" y2="-1.37" width="0.2" layer="21"/>
<wire x1="10.26" y1="-1.37" x2="-10.26" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-10.26" y1="-1.37" x2="-10.26" y2="1.37" width="0.2" layer="21"/>
<rectangle x1="6.096" y1="-0.254" x2="6.604" y2="0.254" layer="51"/>
<rectangle x1="3.556" y1="-0.254" x2="4.064" y2="0.254" layer="51"/>
<rectangle x1="1.016" y1="-0.254" x2="1.524" y2="0.254" layer="51"/>
<rectangle x1="-1.524" y1="-0.254" x2="-1.016" y2="0.254" layer="51"/>
<rectangle x1="-4.064" y1="-0.254" x2="-3.556" y2="0.254" layer="51"/>
<rectangle x1="-6.604" y1="-0.254" x2="-6.096" y2="0.254" layer="51"/>
<rectangle x1="-9.144" y1="-0.254" x2="-8.636" y2="0.254" layer="51"/>
<rectangle x1="8.636" y1="-0.254" x2="9.144" y2="0.254" layer="51"/>
<text x="0" y="2.54" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-2.54" size="1.27" layer="27" align="center">&gt;VALUE</text>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-10.3838" y="-1.4938"/>
<vertex x="10.3838" y="-1.4938"/>
<vertex x="10.3838" y="1.4938"/>
<vertex x="-10.3838" y="1.4938"/>
</polygon>
</package>
<package name="1X08_90" urn="urn:adsk.eagle:footprint:47493510/11" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-8.89" y="-2.77" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="-6.35" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="3" x="-3.81" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="4" x="-1.27" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="5" x="1.27" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="6" x="3.81" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="7" x="6.35" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="8" x="8.89" y="-2.77" drill="1.016" shape="octagon"/>
<text x="0" y="8.89" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-5.08" size="1.27" layer="27" align="center">&gt;VALUE</text>
<wire x1="-10.16" y1="-1.27" x2="-10.16" y2="1.27" width="0.1" layer="51"/>
<wire x1="-10.16" y1="-1.27" x2="-7.62" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-7.62" y1="-1.27" x2="-7.62" y2="1.27" width="0.1" layer="51"/>
<wire x1="-7.62" y1="1.27" x2="-10.16" y2="1.27" width="0.1" layer="51"/>
<wire x1="-7.62" y1="-1.27" x2="-5.08" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-5.08" y1="-1.27" x2="-5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="-5.08" y1="1.27" x2="-7.62" y2="1.27" width="0.1" layer="51"/>
<wire x1="-5.08" y1="-1.27" x2="-2.54" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-1.27" x2="-2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="1.27" x2="-5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-1.27" x2="0" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0" y1="-1.27" x2="0" y2="1.27" width="0.1" layer="51"/>
<wire x1="0" y1="1.27" x2="-2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="0" y1="-1.27" x2="2.54" y2="-1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="-1.27" x2="2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="1.27" x2="0" y2="1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="-1.27" x2="5.08" y2="-1.27" width="0.1" layer="51"/>
<wire x1="5.08" y1="-1.27" x2="5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="5.08" y1="1.27" x2="2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="5.08" y1="-1.27" x2="7.62" y2="-1.27" width="0.1" layer="51"/>
<wire x1="7.62" y1="-1.27" x2="7.62" y2="1.27" width="0.1" layer="51"/>
<wire x1="7.62" y1="1.27" x2="5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="7.62" y1="-1.27" x2="10.16" y2="-1.27" width="0.1" layer="51"/>
<wire x1="10.16" y1="-1.27" x2="10.16" y2="1.27" width="0.1" layer="51"/>
<wire x1="10.16" y1="1.27" x2="7.62" y2="1.27" width="0.1" layer="51"/>
<wire x1="-10.26" y1="1.37" x2="10.26" y2="1.37" width="0.2" layer="21"/>
<wire x1="10.26" y1="1.37" x2="10.26" y2="-1.37" width="0.2" layer="21"/>
<wire x1="10.26" y1="-1.37" x2="-10.26" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-10.26" y1="-1.37" x2="-10.26" y2="1.37" width="0.2" layer="21"/>
<wire x1="-9.21" y1="7.27" x2="-8.57" y2="7.27" width="0.127" layer="51"/>
<wire x1="-8.57" y1="7.27" x2="-8.57" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-8.57" y1="-3.09" x2="-9.21" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-9.21" y1="-3.09" x2="-9.21" y2="7.27" width="0.127" layer="51"/>
<wire x1="-6.67" y1="7.27" x2="-6.03" y2="7.27" width="0.127" layer="51"/>
<wire x1="-6.03" y1="7.27" x2="-6.03" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-6.03" y1="-3.09" x2="-6.67" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-6.67" y1="-3.09" x2="-6.67" y2="7.27" width="0.127" layer="51"/>
<wire x1="-4.13" y1="7.27" x2="-3.49" y2="7.27" width="0.127" layer="51"/>
<wire x1="-3.49" y1="7.27" x2="-3.49" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-3.49" y1="-3.09" x2="-4.13" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-4.13" y1="-3.09" x2="-4.13" y2="7.27" width="0.127" layer="51"/>
<wire x1="-1.59" y1="7.27" x2="-0.95" y2="7.27" width="0.127" layer="51"/>
<wire x1="-0.95" y1="7.27" x2="-0.95" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-0.95" y1="-3.09" x2="-1.59" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-1.59" y1="-3.09" x2="-1.59" y2="7.27" width="0.127" layer="51"/>
<wire x1="0.95" y1="7.27" x2="1.59" y2="7.27" width="0.127" layer="51"/>
<wire x1="1.59" y1="7.27" x2="1.59" y2="-3.09" width="0.127" layer="51"/>
<wire x1="1.59" y1="-3.09" x2="0.95" y2="-3.09" width="0.127" layer="51"/>
<wire x1="0.95" y1="-3.09" x2="0.95" y2="7.27" width="0.127" layer="51"/>
<wire x1="3.49" y1="7.27" x2="4.13" y2="7.27" width="0.127" layer="51"/>
<wire x1="4.13" y1="7.27" x2="4.13" y2="-3.09" width="0.127" layer="51"/>
<wire x1="4.13" y1="-3.09" x2="3.49" y2="-3.09" width="0.127" layer="51"/>
<wire x1="3.49" y1="-3.09" x2="3.49" y2="7.27" width="0.127" layer="51"/>
<wire x1="6.03" y1="7.27" x2="6.67" y2="7.27" width="0.127" layer="51"/>
<wire x1="6.67" y1="7.27" x2="6.67" y2="-3.09" width="0.127" layer="51"/>
<wire x1="6.67" y1="-3.09" x2="6.03" y2="-3.09" width="0.127" layer="51"/>
<wire x1="6.03" y1="-3.09" x2="6.03" y2="7.27" width="0.127" layer="51"/>
<wire x1="8.57" y1="7.27" x2="9.21" y2="7.27" width="0.127" layer="51"/>
<wire x1="9.21" y1="7.27" x2="9.21" y2="-3.09" width="0.127" layer="51"/>
<wire x1="9.21" y1="-3.09" x2="8.57" y2="-3.09" width="0.127" layer="51"/>
<wire x1="8.57" y1="-3.09" x2="8.57" y2="7.27" width="0.127" layer="51"/>
<rectangle x1="-9.21" y1="-3.09" x2="-8.57" y2="7.27" layer="51"/>
<rectangle x1="-6.67" y1="-3.09" x2="-6.03" y2="7.27" layer="51"/>
<rectangle x1="-4.13" y1="-3.09" x2="-3.49" y2="7.27" layer="51"/>
<rectangle x1="-1.59" y1="-3.09" x2="-0.95" y2="7.27" layer="51"/>
<rectangle x1="0.95" y1="-3.09" x2="1.59" y2="7.27" layer="51"/>
<rectangle x1="3.49" y1="-3.09" x2="4.13" y2="7.27" layer="51"/>
<rectangle x1="6.03" y1="-3.09" x2="6.67" y2="7.27" layer="51"/>
<rectangle x1="8.57" y1="-3.09" x2="9.21" y2="7.27" layer="51"/>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-10.3838" y="-3.8238"/>
<vertex x="10.3838" y="-3.8238"/>
<vertex x="10.3838" y="7.5238"/>
<vertex x="-10.3838" y="7.5238"/>
</polygon>
</package>
<package name="1X04" urn="urn:adsk.eagle:footprint:47493541/14" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-3.81" y="0" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="-1.27" y="0" drill="1.016" shape="octagon"/>
<pad name="3" x="1.27" y="0" drill="1.016" shape="octagon"/>
<pad name="4" x="3.81" y="0" drill="1.016" shape="octagon"/>
<wire x1="0.635" y1="1.27" x2="1.905" y2="1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="1.27" x2="2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="0.635" x2="2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="-0.635" x2="1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="0.635" x2="-1.905" y2="1.27" width="0.1" layer="51"/>
<wire x1="-1.905" y1="1.27" x2="-0.635" y2="1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="1.27" x2="0" y2="0.635" width="0.1" layer="51"/>
<wire x1="0" y1="0.635" x2="0" y2="-0.635" width="0.1" layer="51"/>
<wire x1="0" y1="-0.635" x2="-0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-0.635" y1="-1.27" x2="-1.905" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-1.905" y1="-1.27" x2="-2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="0.635" y1="1.27" x2="0" y2="0.635" width="0.1" layer="51"/>
<wire x1="0" y1="-0.635" x2="0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="1.905" y1="-1.27" x2="0.635" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-5.08" y1="0.635" x2="-5.08" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-5.08" y1="0.635" x2="-4.445" y2="1.27" width="0.1" layer="51"/>
<wire x1="-4.445" y1="1.27" x2="-3.175" y2="1.27" width="0.1" layer="51"/>
<wire x1="-3.175" y1="1.27" x2="-2.54" y2="0.635" width="0.1" layer="51"/>
<wire x1="-2.54" y1="0.635" x2="-2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-0.635" x2="-3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-3.175" y1="-1.27" x2="-4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-4.445" y1="-1.27" x2="-5.08" y2="-0.635" width="0.1" layer="51"/>
<wire x1="2.54" y1="0.635" x2="3.175" y2="1.27" width="0.1" layer="51"/>
<wire x1="3.175" y1="1.27" x2="4.445" y2="1.27" width="0.1" layer="51"/>
<wire x1="4.445" y1="1.27" x2="5.08" y2="0.635" width="0.1" layer="51"/>
<wire x1="5.08" y1="0.635" x2="5.08" y2="-0.635" width="0.1" layer="51"/>
<wire x1="5.08" y1="-0.635" x2="4.445" y2="-1.27" width="0.1" layer="51"/>
<wire x1="4.445" y1="-1.27" x2="3.175" y2="-1.27" width="0.1" layer="51"/>
<wire x1="3.175" y1="-1.27" x2="2.54" y2="-0.635" width="0.1" layer="51"/>
<wire x1="-5.18" y1="1.37" x2="5.18" y2="1.37" width="0.2" layer="21"/>
<wire x1="5.18" y1="1.37" x2="5.18" y2="-1.37" width="0.2" layer="21"/>
<wire x1="5.18" y1="-1.37" x2="-5.18" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-5.18" y1="-1.37" x2="-5.18" y2="1.37" width="0.2" layer="21"/>
<rectangle x1="1.016" y1="-0.254" x2="1.524" y2="0.254" layer="51"/>
<rectangle x1="-1.524" y1="-0.254" x2="-1.016" y2="0.254" layer="51"/>
<rectangle x1="-4.064" y1="-0.254" x2="-3.556" y2="0.254" layer="51"/>
<rectangle x1="3.556" y1="-0.254" x2="4.064" y2="0.254" layer="51"/>
<text x="0" y="2.54" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-2.54" size="1.27" layer="27" align="center">&gt;VALUE</text>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-5.3038" y="-1.4938"/>
<vertex x="5.3038" y="-1.4938"/>
<vertex x="5.3038" y="1.4938"/>
<vertex x="-5.3038" y="1.4938"/>
</polygon>
</package>
<package name="1X04_90" urn="urn:adsk.eagle:footprint:47493542/14" library_version="64">
<description>Pin Header</description>
<pad name="1" x="-3.81" y="-2.77" drill="1.016" shape="octagon" first="yes"/>
<pad name="2" x="-1.27" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="3" x="1.27" y="-2.77" drill="1.016" shape="octagon"/>
<pad name="4" x="3.81" y="-2.77" drill="1.016" shape="octagon"/>
<text x="0" y="8.89" size="1.27" layer="25" align="center">&gt;NAME</text>
<text x="0" y="-5.08" size="1.27" layer="27" align="center">&gt;VALUE</text>
<wire x1="-5.08" y1="-1.27" x2="-5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="-5.08" y1="-1.27" x2="-2.54" y2="-1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-1.27" x2="-2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="1.27" x2="-5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="-2.54" y1="-1.27" x2="0" y2="-1.27" width="0.1" layer="51"/>
<wire x1="0" y1="-1.27" x2="0" y2="1.27" width="0.1" layer="51"/>
<wire x1="0" y1="1.27" x2="-2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="0" y1="-1.27" x2="2.54" y2="-1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="-1.27" x2="2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="1.27" x2="0" y2="1.27" width="0.1" layer="51"/>
<wire x1="2.54" y1="-1.27" x2="5.08" y2="-1.27" width="0.1" layer="51"/>
<wire x1="5.08" y1="-1.27" x2="5.08" y2="1.27" width="0.1" layer="51"/>
<wire x1="5.08" y1="1.27" x2="2.54" y2="1.27" width="0.1" layer="51"/>
<wire x1="-5.18" y1="1.37" x2="5.18" y2="1.37" width="0.2" layer="21"/>
<wire x1="5.18" y1="1.37" x2="5.18" y2="-1.37" width="0.2" layer="21"/>
<wire x1="5.18" y1="-1.37" x2="-5.18" y2="-1.37" width="0.2" layer="21"/>
<wire x1="-5.18" y1="-1.37" x2="-5.18" y2="1.37" width="0.2" layer="21"/>
<wire x1="-4.13" y1="7.27" x2="-3.49" y2="7.27" width="0.127" layer="51"/>
<wire x1="-3.49" y1="7.27" x2="-3.49" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-3.49" y1="-3.09" x2="-4.13" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-4.13" y1="-3.09" x2="-4.13" y2="7.27" width="0.127" layer="51"/>
<wire x1="-1.59" y1="7.27" x2="-0.95" y2="7.27" width="0.127" layer="51"/>
<wire x1="-0.95" y1="7.27" x2="-0.95" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-0.95" y1="-3.09" x2="-1.59" y2="-3.09" width="0.127" layer="51"/>
<wire x1="-1.59" y1="-3.09" x2="-1.59" y2="7.27" width="0.127" layer="51"/>
<wire x1="0.95" y1="7.27" x2="1.59" y2="7.27" width="0.127" layer="51"/>
<wire x1="1.59" y1="7.27" x2="1.59" y2="-3.09" width="0.127" layer="51"/>
<wire x1="1.59" y1="-3.09" x2="0.95" y2="-3.09" width="0.127" layer="51"/>
<wire x1="0.95" y1="-3.09" x2="0.95" y2="7.27" width="0.127" layer="51"/>
<wire x1="3.49" y1="7.27" x2="4.13" y2="7.27" width="0.127" layer="51"/>
<wire x1="4.13" y1="7.27" x2="4.13" y2="-3.09" width="0.127" layer="51"/>
<wire x1="4.13" y1="-3.09" x2="3.49" y2="-3.09" width="0.127" layer="51"/>
<wire x1="3.49" y1="-3.09" x2="3.49" y2="7.27" width="0.127" layer="51"/>
<rectangle x1="-4.13" y1="-3.09" x2="-3.49" y2="7.27" layer="51"/>
<rectangle x1="-1.59" y1="-3.09" x2="-0.95" y2="7.27" layer="51"/>
<rectangle x1="0.95" y1="-3.09" x2="1.59" y2="7.27" layer="51"/>
<rectangle x1="3.49" y1="-3.09" x2="4.13" y2="7.27" layer="51"/>
<polygon width="0.1524" layer="39" pour="solid">
<vertex x="-5.3038" y="-3.8238"/>
<vertex x="5.3038" y="-3.8238"/>
<vertex x="5.3038" y="7.5238"/>
<vertex x="-5.3038" y="7.5238"/>
</polygon>
</package>
</packages>
<packages3d>
<package3d name="1X02" urn="urn:adsk.eagle:package:51802571/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X02"/>
</packageinstances>
</package3d>
<package3d name="1X02_90" urn="urn:adsk.eagle:package:51802565/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X02_90"/>
</packageinstances>
</package3d>
<package3d name="1X07" urn="urn:adsk.eagle:package:51802604/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X07"/>
</packageinstances>
</package3d>
<package3d name="1X07_90" urn="urn:adsk.eagle:package:51802607/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X07_90"/>
</packageinstances>
</package3d>
<package3d name="1X08" urn="urn:adsk.eagle:package:51802583/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X08"/>
</packageinstances>
</package3d>
<package3d name="1X08_90" urn="urn:adsk.eagle:package:51802575/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X08_90"/>
</packageinstances>
</package3d>
<package3d name="1X04" urn="urn:adsk.eagle:package:51802636/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X04"/>
</packageinstances>
</package3d>
<package3d name="1X04_90" urn="urn:adsk.eagle:package:51802638/2" type="model">
<description>Pin Header</description>
<packageinstances>
<packageinstance name="1X04_90"/>
</packageinstances>
</package3d>
</packages3d>
<symbols>
<symbol name="PINHD2" urn="urn:adsk.eagle:symbol:47493476/1" library_version="64">
<pin name="1" x="-5.08" y="2.54" visible="pad" length="middle" direction="pas"/>
<pin name="2" x="-5.08" y="0" visible="pad" length="middle" direction="pas"/>
<wire x1="-1.27" y1="-2.54" x2="2.54" y2="-2.54" width="0.1524" layer="94"/>
<wire x1="2.54" y1="-2.54" x2="2.54" y2="5.08" width="0.1524" layer="94"/>
<wire x1="2.54" y1="5.08" x2="-1.27" y2="5.08" width="0.1524" layer="94"/>
<wire x1="-1.27" y1="5.08" x2="-1.27" y2="-2.54" width="0.1524" layer="94"/>
<wire x1="0" y1="2.54" x2="1.27" y2="2.54" width="0.6096" layer="94"/>
<wire x1="0" y1="0" x2="1.27" y2="0" width="0.6096" layer="94"/>
<text x="0" y="7.62" size="1.778" layer="95" align="top-center">&gt;NAME</text>
<text x="0" y="-5.08" size="1.778" layer="96" align="bottom-center">&gt;VALUE</text>
</symbol>
<symbol name="PINHD7" urn="urn:adsk.eagle:symbol:47493480/1" library_version="64">
<pin name="1" x="-5.08" y="7.62" visible="pad" length="middle" direction="pas"/>
<pin name="2" x="-5.08" y="5.08" visible="pad" length="middle" direction="pas"/>
<pin name="3" x="-5.08" y="2.54" visible="pad" length="middle" direction="pas"/>
<pin name="4" x="-5.08" y="0" visible="pad" length="middle" direction="pas"/>
<pin name="5" x="-5.08" y="-2.54" visible="pad" length="middle" direction="pas"/>
<pin name="6" x="-5.08" y="-5.08" visible="pad" length="middle" direction="pas"/>
<pin name="7" x="-5.08" y="-7.62" visible="pad" length="middle" direction="pas"/>
<wire x1="-1.27" y1="-10.16" x2="2.54" y2="-10.16" width="0.1524" layer="94"/>
<wire x1="2.54" y1="-10.16" x2="2.54" y2="10.16" width="0.1524" layer="94"/>
<wire x1="2.54" y1="10.16" x2="-1.27" y2="10.16" width="0.1524" layer="94"/>
<wire x1="-1.27" y1="10.16" x2="-1.27" y2="-10.16" width="0.1524" layer="94"/>
<wire x1="0" y1="7.62" x2="1.27" y2="7.62" width="0.6096" layer="94"/>
<wire x1="0" y1="5.08" x2="1.27" y2="5.08" width="0.6096" layer="94"/>
<wire x1="0" y1="2.54" x2="1.27" y2="2.54" width="0.6096" layer="94"/>
<wire x1="0" y1="0" x2="1.27" y2="0" width="0.6096" layer="94"/>
<wire x1="0" y1="-2.54" x2="1.27" y2="-2.54" width="0.6096" layer="94"/>
<wire x1="0" y1="-5.08" x2="1.27" y2="-5.08" width="0.6096" layer="94"/>
<wire x1="0" y1="-7.62" x2="1.27" y2="-7.62" width="0.6096" layer="94"/>
<text x="0" y="12.7" size="1.778" layer="95" align="top-center">&gt;NAME</text>
<text x="0" y="-12.7" size="1.778" layer="96" align="bottom-center">&gt;VALUE</text>
</symbol>
<symbol name="PINHD8" urn="urn:adsk.eagle:symbol:47493491/1" library_version="64">
<pin name="1" x="-5.08" y="10.16" visible="pad" length="middle" direction="pas"/>
<pin name="2" x="-5.08" y="7.62" visible="pad" length="middle" direction="pas"/>
<pin name="3" x="-5.08" y="5.08" visible="pad" length="middle" direction="pas"/>
<pin name="4" x="-5.08" y="2.54" visible="pad" length="middle" direction="pas"/>
<pin name="5" x="-5.08" y="0" visible="pad" length="middle" direction="pas"/>
<pin name="6" x="-5.08" y="-2.54" visible="pad" length="middle" direction="pas"/>
<pin name="7" x="-5.08" y="-5.08" visible="pad" length="middle" direction="pas"/>
<pin name="8" x="-5.08" y="-7.62" visible="pad" length="middle" direction="pas"/>
<wire x1="-1.27" y1="-10.16" x2="2.54" y2="-10.16" width="0.1524" layer="94"/>
<wire x1="2.54" y1="-10.16" x2="2.54" y2="12.7" width="0.1524" layer="94"/>
<wire x1="2.54" y1="12.7" x2="-1.27" y2="12.7" width="0.1524" layer="94"/>
<wire x1="-1.27" y1="12.7" x2="-1.27" y2="-10.16" width="0.1524" layer="94"/>
<wire x1="0" y1="10.16" x2="1.27" y2="10.16" width="0.6096" layer="94"/>
<wire x1="0" y1="7.62" x2="1.27" y2="7.62" width="0.6096" layer="94"/>
<wire x1="0" y1="5.08" x2="1.27" y2="5.08" width="0.6096" layer="94"/>
<wire x1="0" y1="2.54" x2="1.27" y2="2.54" width="0.6096" layer="94"/>
<wire x1="0" y1="0" x2="1.27" y2="0" width="0.6096" layer="94"/>
<wire x1="0" y1="-2.54" x2="1.27" y2="-2.54" width="0.6096" layer="94"/>
<wire x1="0" y1="-5.08" x2="1.27" y2="-5.08" width="0.6096" layer="94"/>
<wire x1="0" y1="-7.62" x2="1.27" y2="-7.62" width="0.6096" layer="94"/>
<text x="0" y="15.24" size="1.778" layer="95" align="top-center">&gt;NAME</text>
<text x="0" y="-12.7" size="1.778" layer="96" align="bottom-center">&gt;VALUE</text>
</symbol>
<symbol name="PINHD4" urn="urn:adsk.eagle:symbol:47493493/1" library_version="64">
<pin name="1" x="-5.08" y="5.08" visible="pad" length="middle" direction="pas"/>
<pin name="2" x="-5.08" y="2.54" visible="pad" length="middle" direction="pas"/>
<pin name="3" x="-5.08" y="0" visible="pad" length="middle" direction="pas"/>
<pin name="4" x="-5.08" y="-2.54" visible="pad" length="middle" direction="pas"/>
<wire x1="-1.27" y1="-5.08" x2="2.54" y2="-5.08" width="0.1524" layer="94"/>
<wire x1="2.54" y1="-5.08" x2="2.54" y2="7.62" width="0.1524" layer="94"/>
<wire x1="2.54" y1="7.62" x2="-1.27" y2="7.62" width="0.1524" layer="94"/>
<wire x1="-1.27" y1="7.62" x2="-1.27" y2="-5.08" width="0.1524" layer="94"/>
<wire x1="0" y1="5.08" x2="1.27" y2="5.08" width="0.6096" layer="94"/>
<wire x1="0" y1="2.54" x2="1.27" y2="2.54" width="0.6096" layer="94"/>
<wire x1="0" y1="0" x2="1.27" y2="0" width="0.6096" layer="94"/>
<wire x1="0" y1="-2.54" x2="1.27" y2="-2.54" width="0.6096" layer="94"/>
<text x="0" y="10.16" size="1.778" layer="95" align="top-center">&gt;NAME</text>
<text x="0" y="-7.62" size="1.778" layer="96" align="bottom-center">&gt;VALUE</text>
</symbol>
</symbols>
<devicesets>
<deviceset name="PINHD-1X2" urn="urn:adsk.eagle:component:16494866/13" prefix="JP" library_version="64">
<description>Pin Header</description>
<gates>
<gate name="G$1" symbol="PINHD2" x="0" y="0"/>
</gates>
<devices>
<device name="" package="1X02">
<connects>
<connect gate="G$1" pin="1" pad="1"/>
<connect gate="G$1" pin="2" pad="2"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802571/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Straight-2 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
<device name="/90" package="1X02_90">
<connects>
<connect gate="G$1" pin="1" pad="1"/>
<connect gate="G$1" pin="2" pad="2"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802565/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Right Angle-2 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
</devices>
</deviceset>
<deviceset name="PINHD-1X7" urn="urn:adsk.eagle:component:16494883/13" prefix="JP" library_version="64">
<description>Pin Header</description>
<gates>
<gate name="A" symbol="PINHD7" x="0" y="0"/>
</gates>
<devices>
<device name="" package="1X07">
<connects>
<connect gate="A" pin="1" pad="1"/>
<connect gate="A" pin="2" pad="2"/>
<connect gate="A" pin="3" pad="3"/>
<connect gate="A" pin="4" pad="4"/>
<connect gate="A" pin="5" pad="5"/>
<connect gate="A" pin="6" pad="6"/>
<connect gate="A" pin="7" pad="7"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802604/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Straight-7 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
<device name="/90" package="1X07_90">
<connects>
<connect gate="A" pin="1" pad="1"/>
<connect gate="A" pin="2" pad="2"/>
<connect gate="A" pin="3" pad="3"/>
<connect gate="A" pin="4" pad="4"/>
<connect gate="A" pin="5" pad="5"/>
<connect gate="A" pin="6" pad="6"/>
<connect gate="A" pin="7" pad="7"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802607/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Right Angle-7 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
</devices>
</deviceset>
<deviceset name="PINHD-1X8" urn="urn:adsk.eagle:component:16494884/13" prefix="JP" library_version="64">
<description>Pin Header</description>
<gates>
<gate name="A" symbol="PINHD8" x="0" y="0"/>
</gates>
<devices>
<device name="" package="1X08">
<connects>
<connect gate="A" pin="1" pad="1"/>
<connect gate="A" pin="2" pad="2"/>
<connect gate="A" pin="3" pad="3"/>
<connect gate="A" pin="4" pad="4"/>
<connect gate="A" pin="5" pad="5"/>
<connect gate="A" pin="6" pad="6"/>
<connect gate="A" pin="7" pad="7"/>
<connect gate="A" pin="8" pad="8"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802583/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Straight-8 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
<device name="/90" package="1X08_90">
<connects>
<connect gate="A" pin="1" pad="1"/>
<connect gate="A" pin="2" pad="2"/>
<connect gate="A" pin="3" pad="3"/>
<connect gate="A" pin="4" pad="4"/>
<connect gate="A" pin="5" pad="5"/>
<connect gate="A" pin="6" pad="6"/>
<connect gate="A" pin="7" pad="7"/>
<connect gate="A" pin="8" pad="8"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802575/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Right Angle-8 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
</devices>
</deviceset>
<deviceset name="PINHD-1X4" urn="urn:adsk.eagle:component:16494870/13" prefix="JP" library_version="64">
<description>Pin Header</description>
<gates>
<gate name="A" symbol="PINHD4" x="0" y="0"/>
</gates>
<devices>
<device name="" package="1X04">
<connects>
<connect gate="A" pin="1" pad="1"/>
<connect gate="A" pin="2" pad="2"/>
<connect gate="A" pin="3" pad="3"/>
<connect gate="A" pin="4" pad="4"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802636/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Straight-4 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
<device name="/90" package="1X04_90">
<connects>
<connect gate="A" pin="1" pad="1"/>
<connect gate="A" pin="2" pad="2"/>
<connect gate="A" pin="3" pad="3"/>
<connect gate="A" pin="4" pad="4"/>
</connects>
<package3dinstances>
<package3dinstance package3d_urn="urn:adsk.eagle:package:51802638/2"/>
</package3dinstances>
<technologies>
<technology name="">
<attribute name="CATEGORY" value="Connectors" constant="no"/>
<attribute name="TYPE" value="Male Pins" constant="no"/>
<attribute name="DATASHEET" value="" constant="no"/>
<attribute name="MANUFACTURER" value="" constant="no"/>
<attribute name="SUBCATEGORY" value="Headers" constant="no"/>
<attribute name="DESCRIPTION" value="Header-Right Angle-4 Position" constant="no"/>
<attribute name="OPERATING_TEMPERATURE" value="" constant="no"/>
<attribute name="PACKAGE_SIZE" value="" constant="no"/>
<attribute name="PART_STATUS" value="" constant="no"/>
<attribute name="PITCH" value="0.100&quot; (2.54mm)" constant="no"/>
<attribute name="ROHS" value="" constant="no"/>
<attribute name="SERIES" value="" constant="no"/>
<attribute name="THERMALLOSS" value="" constant="no"/>
<attribute name="MPN" value="" constant="no"/>
<attribute name="PACKAGE_TYPE" value="Through Hole" constant="no"/>
</technology>
</technologies>
</device>
</devices>
</deviceset>
</devicesets>
</library>
</libraries>
<attributes>
</attributes>
<variantdefs>
</variantdefs>
<classes>
<class number="0" name="default" width="0" drill="0">
</class>
</classes>
<parts>
<part name="JP11" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X2" device="" package3d_urn="urn:adsk.eagle:package:51802571/2"/>
<part name="JP10" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X7" device="" package3d_urn="urn:adsk.eagle:package:51802604/2"/>
<part name="JP12" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X7" device="" package3d_urn="urn:adsk.eagle:package:51802604/2"/>
<part name="JP14" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X7" device="" package3d_urn="urn:adsk.eagle:package:51802604/2"/>
<part name="JP15" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X7" device="" package3d_urn="urn:adsk.eagle:package:51802604/2"/>
<part name="JP1" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP16" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP2" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP17" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP3" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP18" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP4" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP19" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP5" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP20" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP6" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP21" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP7" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP22" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X8" device="" package3d_urn="urn:adsk.eagle:package:51802583/2"/>
<part name="JP13" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP23" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP24" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP25" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP26" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP27" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP28" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP8" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP9" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X4" device="" package3d_urn="urn:adsk.eagle:package:51802636/2"/>
<part name="JP29" library="Connector" library_urn="urn:adsk.eagle:library:16378166" deviceset="PINHD-1X2" device="" package3d_urn="urn:adsk.eagle:package:51802571/2"/>
</parts>
<sheets>
<sheet>
<plain>
</plain>
<instances>
<instance part="JP11" gate="G$1" x="116.84" y="137.16" smashed="yes">
<attribute name="NAME" x="116.84" y="144.78" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="116.84" y="132.08" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP10" gate="A" x="35.56" y="104.14" smashed="yes">
<attribute name="NAME" x="35.56" y="116.84" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="35.56" y="91.44" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP12" gate="A" x="35.56" y="124.46" smashed="yes">
<attribute name="NAME" x="35.56" y="137.16" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="35.56" y="111.76" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP14" gate="A" x="43.18" y="124.46" smashed="yes" rot="MR0">
<attribute name="NAME" x="43.18" y="137.16" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="43.18" y="111.76" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP15" gate="A" x="43.18" y="104.14" smashed="yes" rot="MR0">
<attribute name="NAME" x="43.18" y="116.84" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="43.18" y="91.44" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP1" gate="A" x="68.58" y="129.54" smashed="yes">
<attribute name="NAME" x="68.58" y="144.78" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="116.84" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP16" gate="A" x="73.66" y="129.54" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="144.78" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="116.84" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP2" gate="A" x="68.58" y="99.06" smashed="yes">
<attribute name="NAME" x="68.58" y="114.3" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="86.36" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP17" gate="A" x="73.66" y="99.06" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="114.3" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="86.36" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP3" gate="A" x="68.58" y="68.58" smashed="yes">
<attribute name="NAME" x="68.58" y="83.82" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="55.88" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP18" gate="A" x="73.66" y="68.58" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="83.82" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="55.88" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP4" gate="A" x="68.58" y="38.1" smashed="yes">
<attribute name="NAME" x="68.58" y="53.34" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="25.4" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP19" gate="A" x="73.66" y="38.1" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="53.34" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="25.4" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP5" gate="A" x="68.58" y="7.62" smashed="yes">
<attribute name="NAME" x="68.58" y="22.86" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="-5.08" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP20" gate="A" x="73.66" y="7.62" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="22.86" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="-5.08" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP6" gate="A" x="68.58" y="-22.86" smashed="yes">
<attribute name="NAME" x="68.58" y="-7.62" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="-35.56" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP21" gate="A" x="73.66" y="-22.86" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="-7.62" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="-35.56" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP7" gate="A" x="68.58" y="-53.34" smashed="yes">
<attribute name="NAME" x="68.58" y="-38.1" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="68.58" y="-66.04" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP22" gate="A" x="73.66" y="-53.34" smashed="yes" rot="MR0">
<attribute name="NAME" x="73.66" y="-38.1" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="73.66" y="-66.04" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP13" gate="A" x="83.82" y="129.54" smashed="yes">
<attribute name="NAME" x="83.82" y="139.7" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="121.92" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP23" gate="A" x="83.82" y="99.06" smashed="yes">
<attribute name="NAME" x="83.82" y="109.22" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="91.44" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP24" gate="A" x="83.82" y="68.58" smashed="yes">
<attribute name="NAME" x="83.82" y="78.74" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="60.96" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP25" gate="A" x="83.82" y="38.1" smashed="yes">
<attribute name="NAME" x="83.82" y="48.26" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="30.48" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP26" gate="A" x="83.82" y="7.62" smashed="yes">
<attribute name="NAME" x="83.82" y="17.78" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="0" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP27" gate="A" x="83.82" y="-22.86" smashed="yes">
<attribute name="NAME" x="83.82" y="-12.7" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="-30.48" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP28" gate="A" x="83.82" y="-53.34" smashed="yes">
<attribute name="NAME" x="83.82" y="-43.18" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="83.82" y="-60.96" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP8" gate="A" x="35.56" y="86.36" smashed="yes">
<attribute name="NAME" x="35.56" y="96.52" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="35.56" y="78.74" size="1.778" layer="96" align="bottom-center"/>
</instance>
<instance part="JP9" gate="A" x="43.18" y="86.36" smashed="yes" rot="MR0">
<attribute name="NAME" x="43.18" y="96.52" size="1.778" layer="95" rot="MR0" align="top-center"/>
<attribute name="VALUE" x="43.18" y="78.74" size="1.778" layer="96" rot="MR0" align="bottom-center"/>
</instance>
<instance part="JP29" gate="G$1" x="116.84" y="121.92" smashed="yes">
<attribute name="NAME" x="116.84" y="129.54" size="1.778" layer="95" align="top-center"/>
<attribute name="VALUE" x="116.84" y="116.84" size="1.778" layer="96" align="bottom-center"/>
</instance>
</instances>
<busses>
</busses>
<nets>
<net name="N$2" class="0">
<segment>
<wire x1="45.72" y1="129.54" x2="48.26" y2="129.54" width="0.1524" layer="91"/>
<pinref part="JP14" gate="A" pin="2"/>
</segment>
</net>
<net name="N$3" class="0">
<segment>
<wire x1="45.72" y1="127" x2="48.26" y2="127" width="0.1524" layer="91"/>
<pinref part="JP14" gate="A" pin="3"/>
</segment>
</net>
<net name="N$4" class="0">
<segment>
<pinref part="JP15" gate="A" pin="2"/>
<wire x1="48.26" y1="109.22" x2="60.96" y2="109.22" width="0.1524" layer="91"/>
<wire x1="60.96" y1="109.22" x2="60.96" y2="91.44" width="0.1524" layer="91"/>
<wire x1="60.96" y1="91.44" x2="63.5" y2="91.44" width="0.1524" layer="91"/>
<pinref part="JP2" gate="A" pin="8"/>
</segment>
</net>
<net name="N$5" class="0">
<segment>
<pinref part="JP15" gate="A" pin="3"/>
<wire x1="48.26" y1="106.68" x2="58.42" y2="106.68" width="0.1524" layer="91"/>
<wire x1="58.42" y1="106.68" x2="58.42" y2="93.98" width="0.1524" layer="91"/>
<pinref part="JP2" gate="A" pin="7"/>
<wire x1="63.5" y1="93.98" x2="58.42" y2="93.98" width="0.1524" layer="91"/>
</segment>
</net>
<net name="N$6" class="0">
<segment>
<wire x1="45.72" y1="119.38" x2="48.26" y2="119.38" width="0.1524" layer="91"/>
<wire x1="93.98" y1="121.92" x2="93.98" y2="119.38" width="0.1524" layer="91"/>
<wire x1="93.98" y1="121.92" x2="78.74" y2="121.92" width="0.1524" layer="91"/>
<wire x1="48.26" y1="119.38" x2="93.98" y2="119.38" width="0.1524" layer="91"/>
<wire x1="93.98" y1="119.38" x2="93.98" y2="91.44" width="0.1524" layer="91"/>
<pinref part="JP14" gate="A" pin="6"/>
<pinref part="JP16" gate="A" pin="8"/>
<pinref part="JP17" gate="A" pin="8"/>
<wire x1="78.74" y1="91.44" x2="93.98" y2="91.44" width="0.1524" layer="91"/>
<wire x1="93.98" y1="91.44" x2="93.98" y2="60.96" width="0.1524" layer="91"/>
<wire x1="93.98" y1="60.96" x2="78.74" y2="60.96" width="0.1524" layer="91"/>
<pinref part="JP18" gate="A" pin="8"/>
<junction x="48.26" y="119.38"/>
<junction x="93.98" y="119.38"/>
<junction x="93.98" y="91.44"/>
</segment>
</net>
<net name="N$7" class="0">
<segment>
<wire x1="71.12" y1="104.14" x2="71.12" y2="60.96" width="0.1524" layer="91"/>
<wire x1="71.12" y1="104.14" x2="63.5" y2="104.14" width="0.1524" layer="91"/>
<pinref part="JP15" gate="A" pin="4"/>
<wire x1="63.5" y1="104.14" x2="48.26" y2="104.14" width="0.1524" layer="91"/>
<wire x1="71.12" y1="60.96" x2="63.5" y2="60.96" width="0.1524" layer="91"/>
<pinref part="JP3" gate="A" pin="8"/>
<pinref part="JP2" gate="A" pin="3"/>
<junction x="63.5" y="104.14"/>
</segment>
</net>
<net name="N$8" class="0">
<segment>
<wire x1="68.58" y1="63.5" x2="68.58" y2="101.6" width="0.1524" layer="91"/>
<wire x1="68.58" y1="101.6" x2="63.5" y2="101.6" width="0.1524" layer="91"/>
<pinref part="JP15" gate="A" pin="5"/>
<pinref part="JP3" gate="A" pin="7"/>
<wire x1="63.5" y1="101.6" x2="48.26" y2="101.6" width="0.1524" layer="91"/>
<wire x1="63.5" y1="63.5" x2="68.58" y2="63.5" width="0.1524" layer="91"/>
<pinref part="JP2" gate="A" pin="4"/>
<junction x="63.5" y="101.6"/>
</segment>
</net>
<net name="N$10" class="0">
<segment>
<wire x1="12.7" y1="109.22" x2="12.7" y2="-60.96" width="0.1524" layer="91"/>
<wire x1="12.7" y1="109.22" x2="30.48" y2="109.22" width="0.1524" layer="91"/>
<pinref part="JP10" gate="A" pin="2"/>
<wire x1="12.7" y1="-60.96" x2="63.5" y2="-60.96" width="0.1524" layer="91"/>
<pinref part="JP7" gate="A" pin="8"/>
</segment>
</net>
<net name="N$11" class="0">
<segment>
<pinref part="JP10" gate="A" pin="1"/>
<wire x1="30.48" y1="111.76" x2="10.16" y2="111.76" width="0.1524" layer="91"/>
<wire x1="10.16" y1="111.76" x2="10.16" y2="-58.42" width="0.1524" layer="91"/>
<wire x1="10.16" y1="-58.42" x2="63.5" y2="-58.42" width="0.1524" layer="91"/>
<pinref part="JP7" gate="A" pin="7"/>
</segment>
</net>
<net name="N$16" class="0">
<segment>
<wire x1="25.4" y1="86.36" x2="25.4" y2="30.48" width="0.1524" layer="91"/>
<wire x1="25.4" y1="30.48" x2="63.5" y2="30.48" width="0.1524" layer="91"/>
<pinref part="JP4" gate="A" pin="8"/>
<pinref part="JP8" gate="A" pin="3"/>
<wire x1="30.48" y1="86.36" x2="25.4" y2="86.36" width="0.1524" layer="91"/>
</segment>
</net>
<net name="N$17" class="0">
<segment>
<wire x1="27.94" y1="83.82" x2="27.94" y2="33.02" width="0.1524" layer="91"/>
<wire x1="27.94" y1="33.02" x2="63.5" y2="33.02" width="0.1524" layer="91"/>
<pinref part="JP4" gate="A" pin="7"/>
<pinref part="JP8" gate="A" pin="4"/>
<wire x1="30.48" y1="83.82" x2="27.94" y2="83.82" width="0.1524" layer="91"/>
</segment>
</net>
<net name="N$21" class="0">
<segment>
<pinref part="JP16" gate="A" pin="1"/>
<pinref part="JP11" gate="G$1" pin="1"/>
<wire x1="111.76" y1="139.7" x2="78.74" y2="139.7" width="0.1524" layer="91"/>
<wire x1="111.76" y1="139.7" x2="106.68" y2="139.7" width="0.1524" layer="91"/>
<wire x1="106.68" y1="139.7" x2="106.68" y2="124.46" width="0.1524" layer="91"/>
<pinref part="JP29" gate="G$1" pin="1"/>
<wire x1="111.76" y1="124.46" x2="106.68" y2="124.46" width="0.1524" layer="91"/>
<wire x1="106.68" y1="124.46" x2="106.68" y2="109.22" width="0.1524" layer="91"/>
<pinref part="JP22" gate="A" pin="1"/>
<wire x1="106.68" y1="109.22" x2="106.68" y2="78.74" width="0.1524" layer="91"/>
<wire x1="106.68" y1="78.74" x2="106.68" y2="48.26" width="0.1524" layer="91"/>
<wire x1="106.68" y1="48.26" x2="106.68" y2="17.78" width="0.1524" layer="91"/>
<wire x1="106.68" y1="17.78" x2="106.68" y2="-12.7" width="0.1524" layer="91"/>
<wire x1="106.68" y1="-12.7" x2="106.68" y2="-43.18" width="0.1524" layer="91"/>
<wire x1="78.74" y1="-43.18" x2="106.68" y2="-43.18" width="0.1524" layer="91"/>
<pinref part="JP21" gate="A" pin="1"/>
<wire x1="78.74" y1="-12.7" x2="106.68" y2="-12.7" width="0.1524" layer="91"/>
<pinref part="JP20" gate="A" pin="1"/>
<wire x1="78.74" y1="17.78" x2="106.68" y2="17.78" width="0.1524" layer="91"/>
<pinref part="JP19" gate="A" pin="1"/>
<wire x1="78.74" y1="48.26" x2="106.68" y2="48.26" width="0.1524" layer="91"/>
<pinref part="JP18" gate="A" pin="1"/>
<wire x1="78.74" y1="78.74" x2="106.68" y2="78.74" width="0.1524" layer="91"/>
<pinref part="JP17" gate="A" pin="1"/>
<wire x1="78.74" y1="109.22" x2="106.68" y2="109.22" width="0.1524" layer="91"/>
<junction x="111.76" y="139.7"/>
<junction x="106.68" y="124.46"/>
<junction x="106.68" y="109.22"/>
<junction x="106.68" y="78.74"/>
<junction x="106.68" y="48.26"/>
<junction x="106.68" y="17.78"/>
<junction x="106.68" y="-12.7"/>
</segment>
</net>
<net name="N$18" class="0">
<segment>
<pinref part="JP18" gate="A" pin="3"/>
<pinref part="JP24" gate="A" pin="1"/>
</segment>
</net>
<net name="N$19" class="0">
<segment>
<pinref part="JP18" gate="A" pin="4"/>
<pinref part="JP24" gate="A" pin="2"/>
</segment>
</net>
<net name="N$22" class="0">
<segment>
<pinref part="JP18" gate="A" pin="5"/>
<pinref part="JP24" gate="A" pin="3"/>
</segment>
</net>
<net name="N$23" class="0">
<segment>
<pinref part="JP18" gate="A" pin="6"/>
<pinref part="JP24" gate="A" pin="4"/>
</segment>
</net>
<net name="N$24" class="0">
<segment>
<pinref part="JP17" gate="A" pin="3"/>
<pinref part="JP23" gate="A" pin="1"/>
</segment>
</net>
<net name="N$25" class="0">
<segment>
<pinref part="JP17" gate="A" pin="4"/>
<pinref part="JP23" gate="A" pin="2"/>
</segment>
</net>
<net name="N$26" class="0">
<segment>
<pinref part="JP17" gate="A" pin="5"/>
<pinref part="JP23" gate="A" pin="3"/>
</segment>
</net>
<net name="N$27" class="0">
<segment>
<pinref part="JP17" gate="A" pin="6"/>
<pinref part="JP23" gate="A" pin="4"/>
</segment>
</net>
<net name="N$28" class="0">
<segment>
<pinref part="JP16" gate="A" pin="3"/>
<pinref part="JP13" gate="A" pin="1"/>
</segment>
</net>
<net name="N$29" class="0">
<segment>
<pinref part="JP16" gate="A" pin="4"/>
<pinref part="JP13" gate="A" pin="2"/>
</segment>
</net>
<net name="N$30" class="0">
<segment>
<pinref part="JP16" gate="A" pin="5"/>
<pinref part="JP13" gate="A" pin="3"/>
</segment>
</net>
<net name="N$31" class="0">
<segment>
<pinref part="JP16" gate="A" pin="6"/>
<pinref part="JP13" gate="A" pin="4"/>
</segment>
</net>
<net name="N$32" class="0">
<segment>
<pinref part="JP19" gate="A" pin="3"/>
<pinref part="JP25" gate="A" pin="1"/>
</segment>
</net>
<net name="N$33" class="0">
<segment>
<pinref part="JP19" gate="A" pin="4"/>
<pinref part="JP25" gate="A" pin="2"/>
</segment>
</net>
<net name="N$34" class="0">
<segment>
<pinref part="JP19" gate="A" pin="5"/>
<pinref part="JP25" gate="A" pin="3"/>
</segment>
</net>
<net name="N$35" class="0">
<segment>
<pinref part="JP19" gate="A" pin="6"/>
<pinref part="JP25" gate="A" pin="4"/>
</segment>
</net>
<net name="N$36" class="0">
<segment>
<pinref part="JP20" gate="A" pin="3"/>
<pinref part="JP26" gate="A" pin="1"/>
</segment>
</net>
<net name="N$37" class="0">
<segment>
<pinref part="JP20" gate="A" pin="4"/>
<pinref part="JP26" gate="A" pin="2"/>
</segment>
</net>
<net name="N$38" class="0">
<segment>
<pinref part="JP20" gate="A" pin="5"/>
<pinref part="JP26" gate="A" pin="3"/>
</segment>
</net>
<net name="N$39" class="0">
<segment>
<pinref part="JP20" gate="A" pin="6"/>
<pinref part="JP26" gate="A" pin="4"/>
</segment>
</net>
<net name="N$40" class="0">
<segment>
<pinref part="JP21" gate="A" pin="3"/>
<pinref part="JP27" gate="A" pin="1"/>
</segment>
</net>
<net name="N$41" class="0">
<segment>
<pinref part="JP21" gate="A" pin="4"/>
<pinref part="JP27" gate="A" pin="2"/>
</segment>
</net>
<net name="N$42" class="0">
<segment>
<pinref part="JP21" gate="A" pin="5"/>
<pinref part="JP27" gate="A" pin="3"/>
</segment>
</net>
<net name="N$43" class="0">
<segment>
<pinref part="JP21" gate="A" pin="6"/>
<pinref part="JP27" gate="A" pin="4"/>
</segment>
</net>
<net name="N$44" class="0">
<segment>
<pinref part="JP22" gate="A" pin="3"/>
<pinref part="JP28" gate="A" pin="1"/>
</segment>
</net>
<net name="N$45" class="0">
<segment>
<pinref part="JP22" gate="A" pin="4"/>
<pinref part="JP28" gate="A" pin="2"/>
</segment>
</net>
<net name="N$46" class="0">
<segment>
<pinref part="JP22" gate="A" pin="5"/>
<pinref part="JP28" gate="A" pin="3"/>
</segment>
</net>
<net name="N$47" class="0">
<segment>
<pinref part="JP22" gate="A" pin="6"/>
<pinref part="JP28" gate="A" pin="4"/>
</segment>
</net>
<net name="N$48" class="0">
<segment>
<pinref part="JP2" gate="A" pin="6"/>
<wire x1="63.5" y1="99.06" x2="63.5" y2="96.52" width="0.1524" layer="91"/>
<pinref part="JP2" gate="A" pin="5"/>
<wire x1="63.5" y1="99.06" x2="53.34" y2="99.06" width="0.1524" layer="91"/>
<wire x1="48.26" y1="132.08" x2="53.34" y2="132.08" width="0.1524" layer="91"/>
<wire x1="53.34" y1="127" x2="63.5" y2="127" width="0.1524" layer="91"/>
<wire x1="63.5" y1="129.54" x2="63.5" y2="127" width="0.1524" layer="91"/>
<wire x1="53.34" y1="132.08" x2="53.34" y2="127" width="0.1524" layer="91"/>
<wire x1="53.34" y1="127" x2="53.34" y2="99.06" width="0.1524" layer="91"/>
<wire x1="53.34" y1="99.06" x2="53.34" y2="66.04" width="0.1524" layer="91"/>
<wire x1="63.5" y1="68.58" x2="63.5" y2="66.04" width="0.1524" layer="91"/>
<wire x1="63.5" y1="66.04" x2="53.34" y2="66.04" width="0.1524" layer="91"/>
<wire x1="53.34" y1="66.04" x2="53.34" y2="35.56" width="0.1524" layer="91"/>
<wire x1="53.34" y1="35.56" x2="63.5" y2="35.56" width="0.1524" layer="91"/>
<wire x1="63.5" y1="35.56" x2="63.5" y2="38.1" width="0.1524" layer="91"/>
<wire x1="63.5" y1="5.08" x2="53.34" y2="5.08" width="0.1524" layer="91"/>
<wire x1="63.5" y1="7.62" x2="63.5" y2="5.08" width="0.1524" layer="91"/>
<pinref part="JP1" gate="A" pin="5"/>
<pinref part="JP1" gate="A" pin="6"/>
<pinref part="JP3" gate="A" pin="5"/>
<pinref part="JP3" gate="A" pin="6"/>
<pinref part="JP4" gate="A" pin="5"/>
<pinref part="JP4" gate="A" pin="6"/>
<pinref part="JP5" gate="A" pin="5"/>
<pinref part="JP5" gate="A" pin="6"/>
<pinref part="JP14" gate="A" pin="1"/>
<wire x1="53.34" y1="35.56" x2="53.34" y2="5.08" width="0.1524" layer="91"/>
<wire x1="53.34" y1="5.08" x2="53.34" y2="-25.4" width="0.1524" layer="91"/>
<wire x1="53.34" y1="-25.4" x2="63.5" y2="-25.4" width="0.1524" layer="91"/>
<pinref part="JP6" gate="A" pin="5"/>
<wire x1="63.5" y1="-22.86" x2="63.5" y2="-25.4" width="0.1524" layer="91"/>
<pinref part="JP6" gate="A" pin="6"/>
<wire x1="53.34" y1="-25.4" x2="53.34" y2="-55.88" width="0.1524" layer="91"/>
<wire x1="53.34" y1="-55.88" x2="63.5" y2="-55.88" width="0.1524" layer="91"/>
<pinref part="JP7" gate="A" pin="5"/>
<wire x1="63.5" y1="-53.34" x2="63.5" y2="-55.88" width="0.1524" layer="91"/>
<pinref part="JP7" gate="A" pin="6"/>
<junction x="63.5" y="99.06"/>
<junction x="53.34" y="99.06"/>
<junction x="53.34" y="127"/>
<junction x="63.5" y="127"/>
<junction x="53.34" y="66.04"/>
<junction x="63.5" y="66.04"/>
<junction x="53.34" y="35.56"/>
<junction x="63.5" y="35.56"/>
<junction x="63.5" y="5.08"/>
<junction x="53.34" y="5.08"/>
<junction x="53.34" y="-25.4"/>
<junction x="63.5" y="-25.4"/>
<junction x="63.5" y="-55.88"/>
</segment>
</net>
<net name="N$20" class="0">
<segment>
<pinref part="JP17" gate="A" pin="2"/>
<pinref part="JP29" gate="G$1" pin="2"/>
<wire x1="111.76" y1="121.92" x2="109.22" y2="121.92" width="0.1524" layer="91"/>
<wire x1="109.22" y1="121.92" x2="109.22" y2="106.68" width="0.1524" layer="91"/>
<wire x1="109.22" y1="106.68" x2="78.74" y2="106.68" width="0.1524" layer="91"/>
<wire x1="109.22" y1="106.68" x2="109.22" y2="76.2" width="0.1524" layer="91"/>
<pinref part="JP22" gate="A" pin="2"/>
<wire x1="78.74" y1="-45.72" x2="109.22" y2="-45.72" width="0.1524" layer="91"/>
<pinref part="JP19" gate="A" pin="2"/>
<wire x1="78.74" y1="45.72" x2="109.22" y2="45.72" width="0.1524" layer="91"/>
<pinref part="JP18" gate="A" pin="2"/>
<wire x1="78.74" y1="76.2" x2="109.22" y2="76.2" width="0.1524" layer="91"/>
<wire x1="109.22" y1="76.2" x2="109.22" y2="45.72" width="0.1524" layer="91"/>
<wire x1="109.22" y1="45.72" x2="109.22" y2="15.24" width="0.1524" layer="91"/>
<pinref part="JP20" gate="A" pin="2"/>
<wire x1="109.22" y1="15.24" x2="109.22" y2="-15.24" width="0.1524" layer="91"/>
<wire x1="109.22" y1="-15.24" x2="109.22" y2="-45.72" width="0.1524" layer="91"/>
<wire x1="78.74" y1="15.24" x2="109.22" y2="15.24" width="0.1524" layer="91"/>
<pinref part="JP21" gate="A" pin="2"/>
<wire x1="78.74" y1="-15.24" x2="109.22" y2="-15.24" width="0.1524" layer="91"/>
<junction x="109.22" y="106.68"/>
<junction x="109.22" y="76.2"/>
<junction x="109.22" y="45.72"/>
<junction x="109.22" y="15.24"/>
<junction x="109.22" y="-15.24"/>
<wire x1="109.22" y1="121.92" x2="109.22" y2="137.16" width="0.1524" layer="91"/>
<junction x="109.22" y="121.92"/>
<pinref part="JP11" gate="G$1" pin="2"/>
<wire x1="111.76" y1="137.16" x2="109.22" y2="137.16" width="0.1524" layer="91"/>
<pinref part="JP16" gate="A" pin="2"/>
<wire x1="78.74" y1="137.16" x2="109.22" y2="137.16" width="0.1524" layer="91"/>
<junction x="78.74" y="137.16"/>
<junction x="109.22" y="137.16"/>
</segment>
</net>
<net name="N$9" class="0">
<segment>
<pinref part="JP6" gate="A" pin="7"/>
<wire x1="63.5" y1="-27.94" x2="15.24" y2="-27.94" width="0.1524" layer="91"/>
<wire x1="15.24" y1="-27.94" x2="15.24" y2="104.14" width="0.1524" layer="91"/>
<wire x1="15.24" y1="104.14" x2="30.48" y2="104.14" width="0.1524" layer="91"/>
<pinref part="JP10" gate="A" pin="4"/>
</segment>
</net>
<net name="N$12" class="0">
<segment>
<pinref part="JP5" gate="A" pin="8"/>
<wire x1="63.5" y1="0" x2="17.78" y2="0" width="0.1524" layer="91"/>
<wire x1="17.78" y1="0" x2="17.78" y2="101.6" width="0.1524" layer="91"/>
<wire x1="17.78" y1="101.6" x2="30.48" y2="101.6" width="0.1524" layer="91"/>
<pinref part="JP10" gate="A" pin="5"/>
</segment>
</net>
<net name="N$13" class="0">
<segment>
<pinref part="JP5" gate="A" pin="7"/>
<wire x1="63.5" y1="2.54" x2="20.32" y2="2.54" width="0.1524" layer="91"/>
<wire x1="20.32" y1="2.54" x2="20.32" y2="96.52" width="0.1524" layer="91"/>
<wire x1="20.32" y1="96.52" x2="30.48" y2="96.52" width="0.1524" layer="91"/>
<pinref part="JP10" gate="A" pin="7"/>
</segment>
</net>
<net name="N$14" class="0">
<segment>
<pinref part="JP10" gate="A" pin="6"/>
<wire x1="30.48" y1="99.06" x2="22.86" y2="99.06" width="0.1524" layer="91"/>
<wire x1="22.86" y1="99.06" x2="22.86" y2="53.34" width="0.1524" layer="91"/>
<wire x1="22.86" y1="53.34" x2="93.98" y2="53.34" width="0.1524" layer="91"/>
<wire x1="93.98" y1="53.34" x2="93.98" y2="30.48" width="0.1524" layer="91"/>
<wire x1="93.98" y1="30.48" x2="78.74" y2="30.48" width="0.1524" layer="91"/>
<pinref part="JP19" gate="A" pin="8"/>
<wire x1="93.98" y1="30.48" x2="93.98" y2="0" width="0.1524" layer="91"/>
<wire x1="93.98" y1="0" x2="78.74" y2="0" width="0.1524" layer="91"/>
<pinref part="JP20" gate="A" pin="8"/>
<wire x1="93.98" y1="0" x2="93.98" y2="-30.48" width="0.1524" layer="91"/>
<wire x1="93.98" y1="-30.48" x2="78.74" y2="-30.48" width="0.1524" layer="91"/>
<pinref part="JP21" gate="A" pin="8"/>
<wire x1="93.98" y1="-30.48" x2="93.98" y2="-60.96" width="0.1524" layer="91"/>
<wire x1="93.98" y1="-60.96" x2="78.74" y2="-60.96" width="0.1524" layer="91"/>
<pinref part="JP22" gate="A" pin="8"/>
<junction x="93.98" y="30.48"/>
<junction x="93.98" y="0"/>
<junction x="93.98" y="-30.48"/>
</segment>
</net>
<net name="N$1" class="0">
<segment>
<pinref part="JP14" gate="A" pin="4"/>
<wire x1="45.72" y1="124.46" x2="48.26" y2="124.46" width="0.1524" layer="91"/>
</segment>
</net>
<net name="N$49" class="0">
<segment>
<pinref part="JP14" gate="A" pin="5"/>
<wire x1="45.72" y1="121.92" x2="48.26" y2="121.92" width="0.1524" layer="91"/>
<wire x1="48.26" y1="121.92" x2="63.5" y2="121.92" width="0.1524" layer="91"/>
<pinref part="JP1" gate="A" pin="8"/>
<junction x="48.26" y="121.92"/>
</segment>
</net>
<net name="N$50" class="0">
<segment>
<pinref part="JP14" gate="A" pin="7"/>
<wire x1="45.72" y1="116.84" x2="48.26" y2="116.84" width="0.1524" layer="91"/>
</segment>
</net>
<net name="N$51" class="0">
<segment>
<pinref part="JP15" gate="A" pin="1"/>
<wire x1="48.26" y1="111.76" x2="45.72" y2="111.76" width="0.1524" layer="91"/>
<wire x1="48.26" y1="111.76" x2="60.96" y2="111.76" width="0.1524" layer="91"/>
<wire x1="60.96" y1="111.76" x2="60.96" y2="124.46" width="0.1524" layer="91"/>
<wire x1="60.96" y1="124.46" x2="63.5" y2="124.46" width="0.1524" layer="91"/>
<pinref part="JP1" gate="A" pin="7"/>
<junction x="48.26" y="111.76"/>
</segment>
</net>
<net name="N$15" class="0">
<segment>
<pinref part="JP15" gate="A" pin="6"/>
<wire x1="48.26" y1="99.06" x2="50.8" y2="99.06" width="0.1524" layer="91"/>
<wire x1="50.8" y1="99.06" x2="50.8" y2="-30.48" width="0.1524" layer="91"/>
<wire x1="50.8" y1="-30.48" x2="63.5" y2="-30.48" width="0.1524" layer="91"/>
<pinref part="JP6" gate="A" pin="8"/>
</segment>
</net>
</nets>
</sheet>
</sheets>
</schematic>
</drawing>
<compatibility>
<note version="8.2" severity="warning">
Since Version 8.2, EAGLE supports online libraries. The ids
of those online libraries will not be understood (or retained)
with this version.
</note>
<note version="8.3" severity="warning">
Since Version 8.3, EAGLE supports URNs for individual library
assets (packages, symbols, and devices). The URNs of those assets
will not be understood (or retained) with this version.
</note>
<note version="8.3" severity="warning">
Since Version 8.3, EAGLE supports the association of 3D packages
with devices in libraries, schematics, and board files. Those 3D
packages will not be understood (or retained) with this version.
</note>
</compatibility>
</eagle>
