"""
Integrates HotSpot simulator in Sniper.

The script is based on the "energystats.py" script.
"""

import sys, os, sim, math, time


def build_dvfs_table(tech):
  # Build a table of (frequency, voltage) pairs.
  # Frequencies should be from high to low, and end with zero (or the lowest possible frequency)
  if tech == 22:
    return [ (2000, 1.0), (1800, 0.9), (1500, 0.8), (1000, 0.7), (0, 0.6) ]
  elif tech == 45:
    return [ (2000, 1.2), (1800, 1.1), (1500, 1.0), (1000, 0.9), (0, 0.8) ]
  else:
    raise ValueError('No DVFS table available for %d nm technology node' % tech)

class HotSpot:
  HEAT_SINK_INCREASE_FACTOR = 2.771590061
  HEAT_SPREADER_INCREASE_FACTOR = 0.8857950303
  GRID_ROWS = 128
  GRID_COLS = 128
  CHIP_ASPECT_RATIO = 1.5

  def setup(self, args):
    args = dict(enumerate((args or '').split(':')))

    self.results_folder = sim.config.output_dir + 'hotspot/'
    self.chip_info_file = self.results_folder + 'hotspot_chip_info.txt'
    # Default power update every 1 ms
    self.calling_interval_ns = long(args.get(0, None) or 1000000) 
    # Set HotSpot calling mode (block or grid)
    self.calling_mode = str(args.get(1, None) or 'block')
    self.dvfs_table = build_dvfs_table(int(sim.config.get('power/technology_node')))
    self.name_last = None
    self.time_last_power = 0
    self.in_stats_write = False
    self.power = {}
    self.power_trace_file = self.results_folder + 'hotspot_power_trace.ptrace'
    self.power_trace_header_written = False;
    self.temperature_trace_file = self.results_folder + 'temperature.ttrace'
    self.statistics_file = self.results_folder + 'hotspot_stats.txt'
    self.floorplan_file = self.results_folder + 'hotspot_nehalem_detailed.flp'

    # Deletes content of hotspot results folder if exists
    if os.path.exists(self.results_folder):
      for the_file in os.listdir(self.results_folder):
        file_path = os.path.join(self.results_folder, the_file)
        try:
          os.unlink(file_path)
        except Exception, e:
          print e
    else:
      os.makedirs(self.results_folder)

    sim.util.Every(self.calling_interval_ns * sim.util.Time.NS, self.periodic, roi_only = True)
   
  def periodic(self, time, time_delta):
    self.update()

  def hook_pre_stat_write(self, prefix):
    if not self.in_stats_write:
      self.update()

  def hook_sim_end(self):
    if self.name_last:
      sim.util.db_delete(self.name_last, True)

    if self.power_trace_header_written == True:
      self.run_temperature_simulation()
    else:
      print >> sys.stderr, "[HOTSPOT] ERROR - The power trace file was not created and the simulation ended."
      print >> sys.stderr, "[HOTSPOT] Possible solution: try to decrease the sampling time." 

  def update(self):
    if sim.stats.time() == self.time_last_power:
      # Time did not advance: don't recompute
      return

    if not self.power or (sim.stats.time() - self.time_last_power >= 10 * sim.util.Time.US):
      # Time advanced significantly, or no power result yet: compute power
      # Save snapshot
      current = 'hotspot-temp%s' % ('B' if self.name_last and self.name_last[-1] == 'A' else 'A')
      self.in_stats_write = True
      sim.stats.write(current)
      self.in_stats_write = False
      # If we also have a previous snapshot: update power
      if self.name_last:
        power = self.run_power(self.name_last, current)
        self.generate_power_trace(power)
      # Clean up previous last
      if self.name_last:
        sim.util.db_delete(self.name_last)
      # Update new last
      self.name_last = current
      self.time_last_power = sim.stats.time()

  def generate_power_trace(self, power):
    # Open power trace file
    fpPowerTrace = file(self.power_trace_file, 'a')

    # Write cores name
    if self.power_trace_header_written == False:
      rowHeader = ''
      for coreIndex in range(sim.config.ncores):
        rowHeader += 'Core_' + str(coreIndex) + '_ExecUnit\t'
        rowHeader += 'Core_' + str(coreIndex) + '_L1Cache\t'
        rowHeader += 'Core_' + str(coreIndex) + '_InstrFetch\t'
        rowHeader += 'Core_' + str(coreIndex) + '_L2Cache\t'
        rowHeader += 'Core_' + str(coreIndex) + '_Paging\t'
      rowHeader += 'L3Cache\n'
      fpPowerTrace.write(rowHeader) # Unit name
      # Generate the floorplan at first call
      self.create_floorplan(power)
      self.power_trace_header_written = True

    # Write runtime dynamic power to power trace file for each core
    row_power = ''
    for coreIndex in range(sim.config.ncores):
      exec_unit_power = power['Core'][coreIndex]['Execution Unit/Runtime Dynamic']
      l1_cache_power = power['Core'][coreIndex]['Load Store Unit/Runtime Dynamic']
      instr_fetch_unit_power = (power['Core'][coreIndex]['Instruction Fetch Unit/Runtime Dynamic'] + power['Core'][coreIndex]['Renaming Unit/Runtime Dynamic'])
      l2_cache_unit_power =power['Core'][coreIndex]['L2/Runtime Dynamic']
      paging_unit_power = power['Core'][coreIndex]['Memory Management Unit/Runtime Dynamic']
      row_power += str(exec_unit_power) + '\t' + str(l1_cache_power) + '\t' + str(instr_fetch_unit_power) + '\t' + str(l2_cache_unit_power) + '\t' + str(paging_unit_power) + '\t'
    row_power += str(power['L3'][0]['Runtime Dynamic']) + '\n'

    fpPowerTrace.write(row_power)
    fpPowerTrace.close()

  def get_vdd_from_freq(self, f):
    # Assume self.dvfs_table is sorted from highest frequency to lowest
    for _f, _v in self.dvfs_table:
      if f >= _f:
        return _v
    assert ValueError('Could not find a Vdd for invalid frequency %f' % f)

  def gen_config(self, outputbase):
    freq = [ sim.dvfs.get_frequency(core) for core in range(sim.config.ncores) ]
    vdd = [ self.get_vdd_from_freq(f) for f in freq ]
    configfile = outputbase+'.cfg'
    cfg = open(configfile, 'w')
    cfg.write('''
[perf_model/core]
frequency[] = %s
[power]
vdd[] = %s
    ''' % (','.join(map(lambda f: '%f' % (f / 1000.), freq)), ','.join(map(str, vdd))))
    cfg.close()
    return configfile

  def run_power(self, name0, name1):
    outputbase = os.path.join(self.results_folder, 'hotspot_power_temp')

    configfile = self.gen_config(outputbase)

    os.system('unset PYTHONHOME; %s -d %s -o %s -c %s --partial=%s:%s --no-graph --no-text' % (
      os.path.join(os.getenv('SNIPER_ROOT'), 'tools/mcpat.py'),
      sim.config.output_dir,
      outputbase,
      configfile,
      name0, name1
    ))

    result = {}
    execfile(outputbase + '.py', {}, result)
    return result['power']

  def create_floorplan(self, result):
    exec_unit_area = result['Core'][0]['Execution Unit/Area'] / 1e6 # mm^2 to m^2
    instr_fetch_unit_area = (result['Core'][0]['Instruction Fetch Unit/Area'] + result['Core'][0]['Renaming Unit/Area']) / 1e6 # mm^2 to m^2
    l1_cache_area = result['Core'][0]['Load Store Unit/Area'] / 1e6 # mm^2 to m^2
    paging_unit_area = result['Core'][0]['Memory Management Unit/Area'] / 1e6 # mm^2 to m^2
    l2_cache_unit_area =result['Core'][0]['L2/Area'] / 1e6 # mm^2 to m^2

    core_area = exec_unit_area  + l1_cache_area + instr_fetch_unit_area + paging_unit_area + l2_cache_unit_area
    chip_area = (core_area * sim.config.ncores) + (result['L3'][0]['Area'] / 1e6)
    chip_height = math.sqrt((chip_area) / self.CHIP_ASPECT_RATIO)
    self.chip_width = chip_area / chip_height
    core_width = self.chip_width / sim.config.ncores if sim.config.ncores <= 4 else self.chip_width / 4
    core_height = core_area / core_width

    fp = file(self.chip_info_file, 'w')
    fp.write("Chip area: " + str(chip_area) + "\n")
    fp.write("Chip width: " + str(self.chip_width) + "\n")
    fp.write("Chip height: " + str(chip_height) + "\n\n")
    fp.write("Core width: " + str(core_width) + "\n")
    fp.write("Core height: " + str(core_height) + "\n")
    fp.write("Core area: " + str(core_height * core_width) + "\n")
    fp.write("Core aspect ratio: " + str(core_height / core_width) + "\n\n")
    fp.write("Heat sink side: " + str(self.chip_width + (self.chip_width * self.HEAT_SINK_INCREASE_FACTOR)) + "\n" )
    fp.write("Heat spreader side: " + str(self.chip_width + (self.chip_width * self.HEAT_SPREADER_INCREASE_FACTOR))  + "\n\n")
    fp.close()

    # Execution units + instruction reordering, sheduling & retirement
    exec_unit_width = core_width
    exec_unit_height = exec_unit_area / exec_unit_width

    # Instruction fetch & L1 Cach + Branch predictor + Instruction Decode & Microcode
    instr_fetch_unit_height = core_height - exec_unit_height
    instr_fetch_unit_width = instr_fetch_unit_area / instr_fetch_unit_height

    # L1 Data Cache + Memory Ordering & Execution
    l1_cache_width = core_width - instr_fetch_unit_width
    l1_cache_height = l1_cache_area / l1_cache_width

    # Level 2 cache
    l2_cache_unit_height = core_height - exec_unit_height - l1_cache_height
    l2_cache_unit_width = l2_cache_unit_area / l2_cache_unit_height

    # Memory Management Unit
    paging_unit_height = l2_cache_unit_height
    paging_unit_width = paging_unit_area / paging_unit_height

    # Floorplan close to the Nehalem processor
    # Line Format: <unit-name>\t<width>\t<height>\t<left-x>\t<bottom-y>
    flp = open(self.floorplan_file,'w')
    lineIndex = 0;
    
    # Place all cores
    for coreIndex in range(sim.config.ncores):
      if coreIndex % 4 == 0 and coreIndex != 0:
        lineIndex += 1;

      core_x = (coreIndex % 4) * core_width
      core_y = core_height * lineIndex

      # Determinate 2d coordinates for each functional unit
      exec_unit_x = 0 + core_x
      exec_unit_y = 0 + core_y

      instr_fetch_unit_x = 0 + core_x
      instr_fetch_unit_y = exec_unit_height + core_y

      l1_cache_x = instr_fetch_unit_width + core_x
      l1_cache_y = exec_unit_height + core_y

      paging_unit_x = instr_fetch_unit_width + core_x
      paging_unit_y = exec_unit_height + l1_cache_height + core_y

      l2_cache_unit_x = instr_fetch_unit_width + paging_unit_width + core_x
      l2_cache_unit_y = exec_unit_height + l1_cache_height + core_y

      flp.write('Core_' + str(coreIndex) + '_ExecUnit ' + str(exec_unit_width) + ' ' + str(exec_unit_height) + ' ' + str(exec_unit_x) + ' ' + str(exec_unit_y) + '\n')
      flp.write('Core_' + str(coreIndex) + '_L1Cache ' + str(l1_cache_width) + ' ' + str(l1_cache_height) + ' ' + str(l1_cache_x) + ' ' + str(l1_cache_y) + '\n')
      flp.write('Core_' + str(coreIndex) + '_InstrFetch ' + str(instr_fetch_unit_width) + ' ' + str(instr_fetch_unit_height) + ' ' + str(instr_fetch_unit_x) + ' ' + str(instr_fetch_unit_y) + '\n')
      flp.write('Core_' + str(coreIndex) + '_L2Cache ' + str(l2_cache_unit_width) + ' ' + str(l2_cache_unit_height) + ' ' + str(l2_cache_unit_x) + ' ' + str(l2_cache_unit_y) + '\n')
      flp.write('Core_' + str(coreIndex) + '_Paging ' + str(paging_unit_width) + ' ' + str(paging_unit_height) + ' ' + str(paging_unit_x) + ' ' + str(paging_unit_y) + '\n')

    # Place the L3 Cache
    l3_width = core_width * sim.config.ncores if sim.config.ncores <= 4 else core_width * 4
    l3_height = (result['L3'][0]['Area'] / 1e6) / l3_width
    # Place it on the new line
    bottom_y = core_height * (lineIndex + 1)
    flp.write('L3Cache ' + str(l3_width) + ' ' + str(l3_height) + ' ' + str(0) + ' ' + str(bottom_y) + '\n')
    flp.close();
    print '[HOTSPOT] Floorplan was created.'

  def run_temperature_simulation(self):
    # Set the cpu frequency [Hz]
    cpu_frequency_ghz = float(sim.config.get('perf_model/core/frequency'))*1e+9

    time_start = time.time()
    sampeling_interval = (self.calling_interval_ns) / cpu_frequency_ghz
    
    print '[HOTSPOT] Starting temperature simulation.'
    print '[HOTSPOT] Calling mode: ' + str(self.calling_mode)
    print '[HOTSPOT] Calling interval: ' + str(sampeling_interval)
    print '[HOTSPOT] Frequency: ' + str(cpu_frequency_ghz)

    # Preheating the chip
    os.system('%s -c %s -f %s -p %s -o %s -steady_file %s -model_type %s -grid_rows %f -grid_cols %f -sampling_intvl %f -base_proc_freq %f -s_sink %f -s_spreader %f >/dev/null' % (
      os.path.join(os.getenv('SNIPER_ROOT'), 'hotspot/hotspot'),
      os.path.join(os.getenv('SNIPER_ROOT'), 'hotspot/hotspot.config'),
      self.floorplan_file,
      self.power_trace_file,
      self.temperature_trace_file,
      self.results_folder + 'hotspot_temperature.init',
      self.calling_mode,
      self.GRID_ROWS,
      self.GRID_COLS,
      sampeling_interval,
      cpu_frequency_ghz,
      self.chip_width + (self.chip_width * self.HEAT_SINK_INCREASE_FACTOR),
      self.chip_width + (self.chip_width * self.HEAT_SPREADER_INCREASE_FACTOR)
    ))

    # Generate temperature trace
    os.system('%s -c %s -init_file %s -f %s -p %s -o %s -model_type %s -grid_rows %f -grid_cols %f -sampling_intvl %f -base_proc_freq %f -s_sink %f -s_spreader %f >/dev/null' % (
      os.path.join(os.getenv('SNIPER_ROOT'), 'hotspot/hotspot'),
      os.path.join(os.getenv('SNIPER_ROOT'), 'hotspot/hotspot.config'),
      self.results_folder + 'hotspot_temperature.init',
      self.floorplan_file,
      self.power_trace_file,
      self.temperature_trace_file,
      self.calling_mode,
      self.GRID_ROWS,
      self.GRID_COLS,
      sampeling_interval,
      cpu_frequency_ghz,
      self.chip_width + (self.chip_width * self.HEAT_SINK_INCREASE_FACTOR),
      self.chip_width + (self.chip_width * self.HEAT_SPREADER_INCREASE_FACTOR)
    ))

    time_finish = time.time()
    simulation_time = time_finish - time_start
    print '[HOTSPOT] Finished temperature simulation.'
    print '[HOTSPOT] Duration: ' + str(simulation_time) + ' seconds.'

    fp = file(self.chip_info_file, 'a')
    fp.write("Simulation duration: " + str(simulation_time) + " seconds.")
    fp.close()

    # Process results
    with open(self.temperature_trace_file) as fp_ttrace:
      temperatures = fp_ttrace.readlines()
    fp_ttrace.close();
    self.process_results(temperatures)

  def process_results(self, results):
    # Compute min, max and averege temperature
    unitNames = {}
    unitTemperatures = {}

    for lineIndex in range(len(results)):
      units = results[lineIndex].rstrip('\n').split('\t')
      # Get unit names from the first line
      if lineIndex == 0:
        for unitIndex in range(len(units)):
          unitNames[unitIndex] = units[unitIndex]
      # Save temperatures for each unit
      elif lineIndex == 1:
        for unitIndex in range(len(units)):
          unitTemperatures[unitNames[unitIndex]] = [units[unitIndex]]
      else:
        for unitIndex in range(len(units)):
          unitTemperatures[unitNames[unitIndex]].append(units[unitIndex])

    fpStats = file(self.statistics_file, 'w')
    for i in range(len(unitNames)):
      if i % 5 == 0 or i == 0: fpStats.write('----------------------------------\n')
      values = map(float, unitTemperatures[unitNames[i]]) # convert string list to float list
      avgVal = float(sum(values))/len(values) if len(values) > 0 else float('nan')
      fpStats.write(str(unitNames[i]) + ':\n')
      fpStats.write('  min: ' + str(min(values)) + '\n')
      fpStats.write('  max: ' + str(max(values)) + '\n')
      fpStats.write('  avg: ' + str(avgVal) + '\n\n')

# All scripts execute in global scope
hotspot = HotSpot()
sim.util.register(hotspot)