#!/usr/bin/env python
#
## Abstract Solver Class
# derived from Patrick Hung's original DifferentialEvolutionSolver
# by mmckerns@caltech.edu

"""
This module contains the base class for mystic solvers, and describes
the mystic solver interface.  The "Solve" method must be overwritten
with the derived solver's optimization algorithm.  In many cases, a
minimal function call interface for a derived solver is provided
along with the derived class.  See `mystic.scipy_optimize`, and the
following for an example.


Usage
=====

A typical call to a mystic solver will roughly follow this example:

    >>> # the function to be minimized and the initial values
    >>> from mystic.models import rosen
    >>> x0 = [0.8, 1.2, 0.7]
    >>> 
    >>> # get monitors and termination condition objects
    >>> from mystic.monitors import Monitor
    >>> stepmon = Monitor()
    >>> evalmon = Monitor()
    >>> from mystic.termination import CandidateRelativeTolerance as CRT
    >>> 
    >>> # instantiate and configure the solver
    >>> from mystic.solvers import NelderMeadSimplexSolver
    >>> solver = NelderMeadSimplexSolver(len(x0))
    >>> solver.SetInitialPoints(x0)
    >>> solver.SetEvaluationMonitor(evalmon)
    >>> solver.SetGenerationMonitor(stepmon)
    >>> solver.enable_signal_handler()
    >>> solver.Solve(rosen, CRT())
    >>> 
    >>> # obtain the solution
    >>> solution = solver.Solution()


An equivalent, yet less flexible, call using the minimal interface is:

    >>> # the function to be minimized and the initial values
    >>> from mystic.models import rosen
    >>> x0 = [0.8, 1.2, 0.7]
    >>> 
    >>> # configure the solver and obtain the solution
    >>> from mystic.solvers import fmin
    >>> solution = fmin(rosen,x0)


Handler
=======

All solvers packaged with mystic include a signal handler that
provides the following options::
    sol: Print current best solution.
    cont: Continue calculation.
    call: Executes sigint_callback, if provided.
    exit: Exits with current best solution.

Handlers are enabled with the 'enable_signal_handler' method,
and are configured through the solver's 'Solve' method.  Handlers
trigger when a signal interrupt (usually, Ctrl-C) is given while
the solver is running.

"""
__all__ = ['AbstractSolver']


import numpy
from numpy import inf, shape, asarray, absolute, asfarray

abs = absolute



class AbstractSolver(object):
    """
AbstractSolver base class for mystic optimizers.
    """

    def __init__(self, dim, **kwds):
        """
Takes one initial input:
    dim      -- dimensionality of the problem.

Additional inputs:
    npop     -- size of the trial solution population.       [default = 1]

Important class members:
    nDim, nPop       = dim, npop
    generations      - an iteration counter.
    evaluations      - an evaluation counter.
    bestEnergy       - current best energy.
    bestSolution     - current best parameter set.           [size = dim]
    popEnergy        - set of all trial energy solutions.    [size = npop]
    population       - set of all trial parameter solutions. [size = dim*npop]
    solution_history - history of bestSolution status.       [StepMonitor.x]
    energy_history   - history of bestEnergy status.         [StepMonitor.y]
    signal_handler   - catches the interrupt signal.
        """
        NP = 1
        if kwds.has_key('npop'): NP = kwds['npop']

        self.nDim             = dim
        self.nPop             = NP
        self._init_popEnergy  = inf
        self.popEnergy	      = [self._init_popEnergy] * NP
        self.population	      = [[0.0 for i in range(dim)] for j in range(NP)]
        self.trialSolution    = [0.0] * dim
        self._map_solver      = False
        self._bestEnergy      = None
        self._bestSolution    = None

        self.signal_handler   = None
        self._handle_sigint   = False
        self._useStrictRange  = False
        self._defaultMin      = [-1e3] * dim
        self._defaultMax      = [ 1e3] * dim
        self._strictMin       = []
        self._strictMax       = []
        self._maxiter         = None
        self._maxfun          = None

        from mystic.monitors import Null, Monitor
        self._evalmon         = Null()
        self._stepmon         = Monitor()
        self._fcalls          = [0]
        self._energy_history  = None
        self._solution_history= None
        self.id               = None     # identifier (use like "rank" for MPI)

        self._constraints     = lambda x: x
        self._penalty         = lambda x: 0.0

        import mystic.termination
        self._EARLYEXIT       = mystic.termination.EARLYEXIT
        return

    def Solution(self):
        """return the best solution"""
        return self.bestSolution

    def __evaluations(self):
        """get the number of function calls"""
        return self._fcalls[0]

    def __generations(self):
        """get the number of iterations"""
        return max(0,len(self.energy_history)-1)
       #return max(0,len(self._stepmon)-1)

    def __energy_history(self):
        """get the energy_history (default: energy_history = _stepmon.y)"""
        if self._energy_history is None: return self._stepmon.y
        return self._energy_history

    def __set_energy_history(self, energy):
        """set the energy_history (energy=None will sync with _stepmon.y)"""
        self._energy_history = energy
        return

    def __solution_history(self):
        """get the solution_history (default: solution_history = _stepmon.x)"""
        if self._solution_history is None: return self._stepmon.x
        return self._solution_history

    def __set_solution_history(self, params):
        """set the solution_history (params=None will sync with _stepmon.x)"""
        self._solution_history = params
        return

    def __bestSolution(self):
        """get the bestSolution (default: bestSolution = population[0])"""
        if self._bestSolution is None: return self.population[0]
        return self._bestSolution

    def __set_bestSolution(self, params):
        """set the bestSolution (params=None will sync with population[0])"""
        self._bestSolution = params
        return

    def __bestEnergy(self):
        """get the bestEnergy (default: bestEnergy = popEnergy[0])"""
        if self._bestEnergy is None: return self.popEnergy[0]
        return self._bestEnergy

    def __set_bestEnergy(self, energy):
        """set the bestEnergy (energy=None will sync with popEnergy[0])"""
        self._bestEnergy = energy
        return

    def SetPenalty(self, penalty):
        """apply a penalty function to the optimization

input::
    - a penalty function of the form: y' = penalty(xk), with y = cost(xk) + y',
      where xk is the current parameter vector. Ideally, this function
      is constructed so a penalty is applied when the desired (i.e. encoded)
      constraints are violated. Equality constraints should be considered
      satisfied when the penalty condition evaluates to zero, while
      inequality constraints are satisfied when the penalty condition
      evaluates to a non-positive number."""
        if not penalty:
            self._penalty = lambda x: 0.0
        elif not callable(penalty):
            raise TypeError, "'%s' is not a callable function" % penalty
        else: #XXX: check for format: y' = penalty(x) ?
            self._penalty = penalty
        return

    def SetConstraints(self, constraints):
        """apply a constraints function to the optimization

input::
    - a constraints function of the form: xk' = constraints(xk),
      where xk is the current parameter vector. Ideally, this function
      is constructed so the parameter vector it passes to the cost function
      will satisfy the desired (i.e. encoded) constraints."""
        if not constraints:
            self._constraints = lambda x: x
        elif not callable(constraints):
            raise TypeError, "'%s' is not a callable function" % constraints
        else: #XXX: check for format: x' = constraints(x) ?
            self._constraints = constraints
        return

    def SetGenerationMonitor(self, monitor):
        """select a callable to monitor (x, f(x)) after each solver iteration"""
        from mystic.monitors import Null, Monitor#, CustomMonitor
        if isinstance(monitor, Monitor):  # is Monitor()
            self._stepmon = monitor
        elif isinstance(monitor, Null) or monitor == Null:  # is Null() or Null
            self._stepmon = Monitor() #XXX: don't allow Null stepmon
        elif hasattr(monitor, '__module__'):  # is CustomMonitor()
            if monitor.__module__ in ['mystic._genSow']:
                self._stepmon = monitor
        else:
            raise TypeError, "'%s' is not a monitor instance" % monitor
        self.energy_history   = self._stepmon.y
        self.solution_history = self._stepmon.x
        return

    def SetEvaluationMonitor(self, monitor):
        """select a callable to monitor (x, f(x)) after each cost function evaluation"""
        from mystic.monitors import Null, Monitor#, CustomMonitor
        if isinstance(monitor, (Null, Monitor) ):  # is Monitor() or Null()
            self._evalmon = monitor
        elif monitor == Null:  # is Null
            self._evalmon = monitor
        elif hasattr(monitor, '__module__'):  # is CustomMonitor()
            if monitor.__module__ in ['mystic._genSow']:
                self._evalmon = monitor
        else:
            raise TypeError, "'%s' is not a monitor instance" % monitor
        return

    def SetStrictRanges(self, min=None, max=None):
        """ensure solution is within bounds

input::
    - min, max: must be a sequence of length self.nDim
    - each min[i] should be <= the corresponding max[i]"""
        #XXX: better to use 'defaultMin,defaultMax' or '-inf,inf' ???
        if min == None: min = self._defaultMin
        if max == None: max = self._defaultMax
        # when 'some' of the bounds are given as 'None', replace with default
        for i in range(len(min)): 
            if min[i] == None: min[i] = self._defaultMin[0]
            if max[i] == None: max[i] = self._defaultMax[0]

        min = asarray(min); max = asarray(max)
        if numpy.any(( min > max ),0):
            raise ValueError, "each min[i] must be <= the corresponding max[i]"
        if len(min) != self.nDim:
            raise ValueError, "bounds array must be length %s" % self.nDim
        self._useStrictRange = True
        self._strictMin = min
        self._strictMax = max
        return

    def _clipGuessWithinRangeBoundary(self, x0): #FIXME: use self.trialSolution?
        """ensure that initial guess is set within bounds

input::
    - x0: must be a sequence of length self.nDim"""
       #if len(x0) != self.nDim: #XXX: unnecessary w/ self.trialSolution
       #    raise ValueError, "initial guess must be length %s" % self.nDim
        x0 = asarray(x0)
        lo = self._strictMin
        hi = self._strictMax
        # crop x0 at bounds
        x0[x0<lo] = lo[x0<lo]
        x0[x0>hi] = hi[x0>hi]
        return x0

    def SetInitialPoints(self, x0, radius=0.05):
        """Set Initial Points with Guess (x0)

input::
    - x0: must be a sequence of length self.nDim
    - radius: generate random points within [-radius*x0, radius*x0]
        for i!=0 when a simplex-type initial guess in required"""
        x0 = asfarray(x0)
        rank = len(x0.shape)
        if rank is 0:
            x0 = asfarray([x0])
            rank = 1
        if not -1 < rank < 2:
            raise ValueError, "Initial guess must be a scalar or rank-1 sequence."
        if len(x0) != self.nDim:
            raise ValueError, "Initial guess must be length %s" % self.nDim

        #slightly alter initial values for solvers that depend on randomness
        min = x0*(1-radius)
        max = x0*(1+radius)
        numzeros = len(x0[x0==0])
        min[min==0] = asarray([-radius for i in range(numzeros)])
        max[max==0] = asarray([radius for i in range(numzeros)])
        self.SetRandomInitialPoints(min,max)
        #stick initial values in population[i], i=0
        self.population[0] = x0.tolist()
    
    def SetRandomInitialPoints(self, min=None, max=None):
        """Generate Random Initial Points within given Bounds

input::
    - min, max: must be a sequence of length self.nDim
    - each min[i] should be <= the corresponding max[i]"""
        if min == None: min = self._defaultMin
        if max == None: max = self._defaultMax
       #if numpy.any(( asarray(min) > asarray(max) ),0):
       #    raise ValueError, "each min[i] must be <= the corresponding max[i]"
        if len(min) != self.nDim or len(max) != self.nDim:
            raise ValueError, "bounds array must be length %s" % self.nDim
        # when 'some' of the bounds are given as 'None', replace with default
        for i in range(len(min)): 
            if min[i] == None: min[i] = self._defaultMin[0]
            if max[i] == None: max[i] = self._defaultMax[0]
        import random
        #generate random initial values
        for i in range(len(self.population)):
            for j in range(self.nDim):
                self.population[i][j] = random.uniform(min[j],max[j])

    def SetMultinormalInitialPoints(self, mean, var = None):
        """Generate Initial Points from Multivariate Normal.

input::
    - mean must be a sequence of length self.nDim
    - var can be...
        None: -> it becomes the identity
        scalar: -> var becomes scalar * I
        matrix: -> the variance matrix. must be the right size!
        """
        from numpy.random import multivariate_normal
        assert(len(mean) == self.nDim)
        if var == None:
            var = numpy.eye(self.nDim)
        else:
            try: # scalar ?
                float(var)
            except: # nope. var better be matrix of the right size (no check)
                pass
            else:
                var = var * numpy.eye(self.nDim)
        for i in range(len(self.population)):
            self.population[i] = multivariate_normal(mean, var).tolist()
        return

    def enable_signal_handler(self):
        """enable workflow interrupt handler while solver is running"""
        self._handle_sigint = True

    def disable_signal_handler(self):
        """disable workflow interrupt handler while solver is running"""
        self._handle_sigint = False

    def _generateHandler(self,sigint_callback):
        """factory to generate signal handler

Available switches::
    - sol  --> Print current best solution.
    - cont --> Continue calculation.
    - call --> Executes sigint_callback, if provided.
    - exit --> Exits with current best solution.
"""
        def handler(signum, frame):
            import inspect
            print inspect.getframeinfo(frame)
            print inspect.trace()
            while 1:
                s = raw_input(\
"""
 
 Enter sense switch.

    sol:  Print current best solution.
    cont: Continue calculation.
    call: Executes sigint_callback [%s].
    exit: Exits with current best solution.

 >>> """ % sigint_callback)
                if s.lower() == 'sol': 
                    print self.bestSolution
                elif s.lower() == 'cont': 
                    return
                elif s.lower() == 'call': 
                    # sigint call_back
                    if sigint_callback is not None:
                        sigint_callback(self.bestSolution)
                elif s.lower() == 'exit': 
                    self._EARLYEXIT = True
                    return
                else:
                    print "unknown option : %s" % s
            return
        self.signal_handler = handler
        return

    def SetEvaluationLimits(self, generations=None, evaluations=None, **kwds):
        """set limits for generations and/or evaluations

input::
    - generations = maximum number of solver iterations (i.e. steps)
    - evaluations  = maximum number of function evaluations"""
        self._maxiter = generations
        self._maxfun = evaluations
        # backward compatibility
        if kwds.has_key('maxiter'):
            self._maxiter = kwds['maxiter']
        if kwds.has_key('maxfun'):
            self._maxfun = kwds['maxfun']
        return

    def _terminated(self, termination, disp=False, info=False):
        # check for termination messages
        msg = termination(self, info=True)
        lim = "EvaluationLimits with %s" % {'evaluations':self._maxfun,
                                            'generations':self._maxiter}

        # push solver internals to scipy.optimize.fmin interface
        if self._fcalls[0] >= self._maxfun and self._maxfun is not None:
            msg = lim #XXX: prefer the default stop ?
            if disp:
                print "Warning: Maximum number of function evaluations has "\
                      "been exceeded."
        elif self.generations >= self._maxiter and self._maxiter is not None:
            msg = lim #XXX: prefer the default stop ?
            if disp:
                print "Warning: Maximum number of iterations has been exceeded"
        elif msg and disp:
            print "Optimization terminated successfully."
            print "         Current function value: %f" % self.bestEnergy
            print "         Iterations: %d" % self.generations
            print "         Function evaluations: %d" % self._fcalls[0]

        if info:
            return msg
        return bool(msg)

    def Solve(self, func, termination, sigint_callback=None,
                                       ExtraArgs=(), **kwds):
        """solve function 'func' with given termination conditions

*** this method must be overwritten ***"""
        raise NotImplementedError, "must be overwritten..."

    # extensions to the solver interface
    evaluations = property(__evaluations )
    generations = property(__generations )
    energy_history = property(__energy_history,__set_energy_history )
    solution_history = property(__solution_history,__set_solution_history )
    bestEnergy = property(__bestEnergy,__set_bestEnergy )
    bestSolution = property(__bestSolution,__set_bestSolution )
    pass


if __name__=='__main__':
    help(__name__)

# end of file
