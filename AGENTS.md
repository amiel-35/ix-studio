# For agents working on this repository

Read this before you change anything, whatever your goal says. It holds for every goal passed to an agent that works
alone on this repository, in the cloud or on a machine.

## One deliverable increment, not the state of the art

1. When you are done, the person can do one more thing in the studio, end to end, even poorly. Open your pull request
   with the sentence "I give X, I get Y". If that sentence needs an "and", it is two increments: deliver the first.
2. The smallest thing that works: between two ways, take the one with the least code and the fewest files touched.
3. No state of the art: do not generalise, do not plan for cases your goal does not name, add no option, no setting,
   no abstraction, no "extensible" format. What would be nice to do along the way goes in your pull request under
   "for later", not in the code.
4. If a constraint pushes you towards lacework, stop at what is simple and say so plainly in your pull request.
5. What is generated is shown and can be corrected before it is used.
6. If your increment cannot be read in a quarter of an hour, it is too big: deliver the first half that works, and say
   what is left.

## For whoever writes a goal

- One goal, one increment, said in one user sentence: "I give X, I get Y".
- The smallest increment that brings the user something new; not a foundation, not a technical layer for later.
- Name in one line what waits, so that the agent does not build it.
- Goals may run in parallel, one per increment; two goals that touch the same files say so, since their branches will
  meet at the merge.
