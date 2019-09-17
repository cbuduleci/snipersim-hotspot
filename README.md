# snipersim-hotspot
Integration of HotSpot simulator in Sniper. Ads to Sniper the ability of thermal analysis of the microarchitecture.
More detalis can be found in [here](https://www.researchgate.net/publication/267039533_Enhancing_the_Sniper_Simulator_with_Thermal_Measurement "Paper") [1].

# Usage
In order to use it the script must be copied in the "scripts" folder that lays in the Sniper simulator installation location. The HotSpot simulator must be also present and compiled inside the Sniper folder in a separate folder named "hotspot".

To run the script you must append the following to the "run-sniper" command: "-s hotspot:p1:p2". Where p1 is the script calling interval and p2 represents the simulation method (block or grid).

For example: "-s hotspot:500000:block".

# Restrictions
Please take into account the following restrictions when using this script:
- heterogeneous configurations are not supported yet;
- the cores are placed 4 per row if the number of cores is bigger than 4. (I am attaching a floorplan example for 4 and 16 cores).

# Used tools
- Sniper 5.3 [2]
- Hotspot 5.02 [3]

# References
- [1] Enhancing the Sniper Simulator with Thermal Measurement (https://www.researchgate.net/publication/267039533_Enhancing_the_Sniper_Simulator_with_Thermal_Measurement) 
- [2] Sniper (https://snipersim.org/w/The_Sniper_Multi-Core_Simulator)
- [3] Hotspot (http://lava.cs.virginia.edu/HotSpot/)
