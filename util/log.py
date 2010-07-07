"""
Tracks application events, both directing them to attached listeners and
keeping a record of them. A limited space is provided for old events, keeping
and trimming them on a per-runlevel basis (ie, too many DEBUG events will only
result in entries from that runlevel being dropped). All functions are thread
safe.
"""

import time
from sys import maxint
from threading import RLock

# logging runlevels
DEBUG, INFO, NOTICE, WARN, ERR = range(1, 6)
RUNLEVEL_STR = {DEBUG: "DEBUG", INFO: "INFO", NOTICE: "NOTICE", WARN: "WARN", ERR: "ERR"}

# provides thread safety for logging operations
LOG_LOCK = RLock()

# chronologically ordered records of events for each runlevel, stored as tuples
# consisting of: (time, message)
_backlog = dict([(level, []) for level in range(1, 6)])

# mapping of runlevels to the listeners interested in receiving events from it
_listeners = dict([(level, []) for level in range(1, 6)])

CONFIG = {"cache.armLog.size": 1000, "cache.armLog.trimSize": 200}

def loadConfig(config):
  config.update(CONFIG)
  
  # ensures sane config values
  CONFIG["cache.armLog.size"] = max(10, CONFIG["cache.armLog.size"])
  CONFIG["cache.armLog.trimSize"] = max(5, min(CONFIG["cache.armLog.trimSize"], CONFIG["cache.armLog.size"] / 2))

def strToRunlevel(runlevelStr):
  """
  Converts runlevel strings ("DEBUG", "INFO", "NOTICE", etc) to their
  corresponding enumeations. This isn't case sensitive and provides None if
  unrecognized.
  
  Arguments:
    runlevelStr - string to be converted to runlevel
  """
  
  if not runlevelStr: return None
  
  runlevelStr = runlevelStr.upper()
  for enum, level in RUNLEVEL_STR.items():
    if level == runlevelStr: return enum
  
  return None

def runlevelToStr(runlevelEnum):
  """
  Converts runlevel enumerations to corresponding string. If unrecognized then
  this provides "NONE".
  
  Arguments:
    runlevelEnum - enumeration to be converted to string
  """
  
  if runlevelEnum in RUNLEVEL_STR: return RUNLEVEL_STR[runlevelEnum]
  else: return "NONE"

def log(level, msg, eventTime = None):
  """
  Registers an event, directing it to interested listeners and preserving it in
  the backlog. If the level is None then this is a no-op.
  
  Arguments:
    level     - runlevel corresponding to the message severity
    msg       - string associated with the message
    eventTime - unix time at which the event occurred, current time if undefined
  """
  
  if not level: return
  if eventTime == None: eventTime = time.time()
  
  LOG_LOCK.acquire()
  try:
    newEvent = (eventTime, msg)
    eventBacklog = _backlog[level]
    
    # inserts the new event into the backlog
    if not eventBacklog or eventTime >= eventBacklog[-1][0]:
      # newest event - append to end
      eventBacklog.append(newEvent)
    elif eventTime <= eventBacklog[0][0]:
      # oldest event - insert at start
      eventBacklog.insert(0, newEvent)
    else:
      # somewhere in the middle - start checking from the end
      for i in range(len(eventBacklog) - 1, -1, -1):
        if eventBacklog[i][0] <= eventTime:
          eventBacklog.insert(i + 1, newEvent)
          break
    
    # truncates backlog if too long
    toDelete = len(eventBacklog) - CONFIG["cache.armLog.size"]
    if toDelete >= 0: del eventBacklog[: toDelete + CONFIG["cache.armLog.trimSize"]]
    
    # notifies listeners
    for callback in _listeners[level]:
      callback(RUNLEVEL_STR[level], msg, eventTime)
  finally:
    LOG_LOCK.release()

def addListener(level, callback):
  """
  Directs future events to the given callback function. The runlevels passed on
  to listeners are provided as the corresponding strings ("DEBUG", "INFO",
  "NOTICE", etc), and times in POSIX (unix) time.
  
  Arguments:
    level    - event runlevel the listener should be notified of
    callback - functor that'll accept the events, expected to be of the form:
               myFunction(level, msg, time)
  """
  
  if not callback in _listeners[level]:
    _listeners[level].append(callback)

def addListeners(levels, callback, dumpBacklog = False):
  """
  Directs future events of multiple runlevels to the given callback function.
  
  Arguments:
    levels      - list of runlevel events the listener should be notified of
    callback    - functor that'll accept the events, expected to be of the
                  form: myFunction(level, msg, time)
    dumpBacklog - if true, any past events of the designated runlevels will be
                  provided to the listener before returning (in chronological
                  order)
  """
  
  LOG_LOCK.acquire()
  try:
    for level in levels: addListener(level, callback)
    
    if dumpBacklog:
      for level, msg, eventTime in _getEntries(levels):
        callback(RUNLEVEL_STR[level], msg, eventTime)
  finally:
    LOG_LOCK.release()

def removeListener(level, callback):
  """
  Stops listener from being notified of further events. This returns true if a
  listener's removed, false otherwise.
  
  Arguments:
    level    - runlevel the listener to be removed
    callback - functor to be removed
  """
  
  if callback in _listeners[level]:
    _listeners[level].remove(callback)
    return True
  else: return False

def _getEntries(levels):
  """
  Generator for providing past events belonging to the given runlevels (in
  chronological order). This should be used under the LOG_LOCK to prevent
  concurrent modifications.
  
  Arguments:
    levels - runlevels for which events are provided
  """
  
  # drops any runlevels if there aren't entries in it
  toRemove = [level for level in levels if not _backlog[level]]
  for level in toRemove: levels.remove(level)
  
  # tracks where unprocessed entries start in the backlog
  backlogPtr = dict([(level, 0) for level in levels])
  
  while levels:
    earliestLevel, earliestMsg, earliestTime = None, "", maxint
    
    # finds the earliest unprocessed event
    for level in levels:
      entry = _backlog[level][backlogPtr[level]]
      
      if entry[0] < earliestTime:
        earliestLevel, earliestMsg, earliestTime = level, entry[1], entry[0]
    
    yield (earliestLevel, earliestMsg, earliestTime)
    
    # removes runlevel if there aren't any more entries
    backlogPtr[earliestLevel] += 1
    if len(_backlog[earliestLevel]) <= backlogPtr[earliestLevel]:
      levels.remove(earliestLevel)

