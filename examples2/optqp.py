#!/usr/bin/env python
#
# Problem definition:
# Example in reference documentation for scipy.optimize
# http://docs.scipy.org/doc/scipy/reference/tutorial/optimize.html
# 
# Author: Mike McKerns (mmckerns @caltech and @uqfoundation)
# Copyright (c) 1997-2015 California Institute of Technology.
# License: 3-clause BSD.  The full license text is available at:
#  - http://trac.mystic.cacr.caltech.edu/project/mystic/browser/mystic/LICENSE
'''
    Maximize: f = 2*x[0]*x[1] + 2*x[0] - x[0]**2 - 2*x[1]**2
  
    Subject to:    x[0]**3 - x[1] == 0
                             x[1] >= 1
'''

def objective(x):
    return 2*x[0]*x[1] + 2*x[0] - x[0]**2 - 2*x[1]**2

equations = """
x0**3 - x1 == 0.0
"""
bounds = [(None, None),(1.0, None)]

# with penalty='penalty' applied, solution is:
xs = [1,1]
ys = -1.0

from mystic.symbolic import generate_conditions, generate_penalty
pf = generate_penalty(generate_conditions(equations), k=1e4)

# inverted objective, used in solving for the maximum
_objective = lambda x: -objective(x)


if __name__ == '__main__':

  from mystic.solvers import diffev2, fmin_powell
  from mystic.math import almostEqual

  result = diffev2(_objective, x0=bounds, bounds=bounds, penalty=pf, npop=40, ftol=1e-8, gtol=100, disp=False, full_output=True)
  assert almostEqual(result[0], xs, rel=2e-2)
  assert almostEqual(result[1], ys, rel=2e-2)

  result = fmin_powell(_objective, x0=[-1.0,1.0], bounds=bounds, penalty=pf, disp=False, full_output=True)
  assert almostEqual(result[0], xs, rel=2e-2)
  assert almostEqual(result[1], ys, rel=2e-2)


# EOD