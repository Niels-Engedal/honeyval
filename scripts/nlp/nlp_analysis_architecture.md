# NLP Analysis Architecture

This document contain initial thoughts on how to structure the analysis pipeline. The architecture should be modular and flexibible, which allows us to answer a diverse set of research questions with different operationalizations. Everything should be done on multiple levels across any relevant subsets. This is mostly for the flexibility until we hone in on our research questions and specific operationalizations after further litterature review. We should be carefull about harking and multiple comparisons without proper statistical correction. We propose the following initial analysis architecture:

## Preprocessing - preproc.py
All preprocesing should be done on different subsets:
- **Application Subsets:**
  - Overall (`--all_apps`)
  - By Application (`--app "wiki"`, `--app "forum"`, etc.)
  - **Prompt Type Subsets:**
    - Vulnerable (`--prompt vulnerable`)
    - Misaligned (`--prompt misaligned`)
    - Combined (`--prompt combined`)
    - **Agent Type Subsets:**
      - Attacker (`--agent attacker`)
      - Defender (`--agent defender`)

1. **Parse agent interactions (`parse_experiments_outputs.py`)**
   - Parse the following scores: interaction length, cost advantage, detection TPR, and Test Pass@1.
   - Parse strategy text statements into texts on each of the levels described below for the embeddings.
   - Store scores and texts intelligently for persistence, caring for interpretability and ease of use when embedding.

2. **Create embeddings (`embed.py`)**
   - Each strategy statement for each agent (`--statement_level`)
   - All responses in one interaction for one agent only (`--agent_level`)
   - Complete interactions chronologically, cross-agent level (`--interaction_level`)
   - Then store embeddings for persistance, again caring for interpretability and ease of use for concepts vector projection.

## Concept Vector Projection - cvp.py
Concept vector projection can be done directly from the texts using turftopic, but turftopic also allows us to use precomputed document embeddings, which we utilize to keep our pipeline modular and easy to experiment with without having to precompute embeddings again and again, when iterating on the concept vector projection script. However, again, be carefull about seed tuning. Choose the most rigouros seed before running concept vector projects and statistical tests. The concept vector projection implementation in turftopic does however require a mathching active encoder to when using the ConceptVectorProjection to encode the concept seeds, which we therefore do in this script along with the projection. The steps is therefore as follows:
1. Define seeds for enticingness and believability
2. Define ConceptVectorProjection
3. Fit ConceptVectorProjection for each document subset and level as described above but do it combined, so their projection scores lie in the same vector space
4. Then store projections for persitancy, again caring for interpretability and ease of use for the upcomming statistical tests.

## Statistical modelling and tests - stats.py
At the moment we intend investigate the following research questions:

**RQ1:** Does a honeypot defender agent with a prompt intending to fake vulnerabilities increase the attacker enticingness, relative to an agent with a prompt intending to mislead the attacker to believe it is not in a honeypot, as expressed by a concept vector projection, represented in the defender strategy and the attacker strategy. 

**RQ2:** Does a honeypot defender agent with a prompt intending to mislead the attacker to believe it is not in a honeypot increase the attacker believability, relative to an agent with a prompt intending to fake vulnerabilities, as expressed by a concept vector projection, represented in the defender strategy and the attacker strategy. 

**RQ3:** Does a honeypot defender agent with a prompt intending to fake vulnerabilities increase the defender enticingness, relative to an agent with a prompt intending to mislead the attacker to believe it is not in a honeypot, as expressed by a concept vector projection, represented in the defender strategy and the attacker strategy. 

**RQ4:** Does a honeypot defender agent with a prompt intending to mislead the attacker to believe it is not in a honeypot increase the defender believability, relative to an agent with a prompt intending to fake vulnerabilities, as expressed by a concept vector projection, represented in the defender strategy and the attacker strategy. 

**RQ5:** Does the enticingness, as expressed by a concept vector projection, correlate between the attacker and defender agent strategies throughout the interaction.

**RQ6:** Does the believability, as expressed by a concept vector projection, correlate between the attacker and defender agent strategies throughout the interaction. 

**RQ7:** How does enticingness and believability correlate with interaction length, cost advantage, detection TPR and Test Pass@1. 

Currently we expect to analyse each of the questions on the following subsets and levels with the proposed statistical tests:
| RQ | Subsets   | Levels                                   | Test                                                                                        |
|----|-----------|------------------------------------------|---------------------------------------------------------------------------------------------|
| 1  | all apps  | --statement_level                        |  Linear Mixed-Effects Model per agent                                                       |
| 2  | all apps  | --statement_level                        | Linear Mixed-Effects Model per agent                                                        |
| 3  | all apps  | --statement_level                        | Repeated Measures Correlation                                                |
| 4  | all apps  | --statement_level                        | Repeated Measures Correlation                                                |
| 5  | all apps  | --agent <br>or --interaction<br> or both |  Generalized Linear Mixed-Effects Model per metric <br> (if --agent then per agent as well) |

If the above is what we decide on we only need necessary subsets and levels for these analyses. We have not figured out how we correct for muliple comparisons for the above proposed statistical tests and if we should perform fever statistical tests to decrease the chances of multiple comparison issues by instead only choosing the most important tests. 

How could each of the statistical models look:

**RQ1:**

$$
AttackerEnticingnessCVP_{ijk} = \beta_0 + \beta_1 \cdot Prompt_i + u_{app(j)} + u_{interaction(jk)} + \epsilon_{ijk}
$$ 

$AttackerEnticingnessCVP_{ijk}$: Attacker agent enticingness concept vector projection score for statement *i* within interaction *k* and application *j*\
$\beta_0$: baseline intercept\
$\beta_1$: fixed effect of target prompt\
$Prompt_i$: the prompt, either vulnerable or misleading, that generated statement *i*\
$u_{app(j)}$: the random intercept for each application *j* (we could possibly add a random slope, but we think this will add uneccessary complexity)\
$u_{interaction(jk)}$: the nested random intercept for each interaction *k* within application *j*\
$\epsilon_{ijk}$: residual error\

**RQ2:**

$$
AttackerBelievabilityCVP_{ijk} = \beta_0 + \beta_1 \cdot Prompt_i + u_{app(j)} + u_{interaction(jk)} + \epsilon_{ijk}
$$ 

$AttackerBelievabilityCVP_{ijk}$: Attacker agent believability concept vector projection score for statement *i* within interaction *k* and application *j*\
$\beta_0$: baseline intercept\
$\beta_1$: fixed effect of target prompt\
$Prompt_i$: the prompt, either vulnerable or misleading, that generated statement *i*\
$u_{app(j)}$: the random intercept for each application *j* (we could possibly add a random slope, but we think this will add uneccessary complexity)\
$u_{interaction(jk)}$: the nested random intercept for each interaction *k* within application *j*\
$\epsilon_{ijk}$: residual error\

**RQ3:**

$$
DefenderEnticingnessCVP_{ijk} = \beta_0 + \beta_1 \cdot Prompt_i + u_{app(j)} + u_{interaction(jk)} + \epsilon_{ijk}
$$ 

$DefenderEnticingnessCVP_{ijk}$: Defender agent enticingness concept vector projection score for statement *i* within interaction *k* and application *j*\
$\beta_0$: baseline intercept\
$\beta_1$: fixed effect of target prompt\
$Prompt_i$: the prompt, either vulnerable or misleading, that generated statement *i*\
$u_{app(j)}$: the random intercept for each application *j* (we could possibly add a random slope, but we think this will add uneccessary complexity)\
$u_{interaction(jk)}$: the nested random intercept for each interaction *k* within application *j*\
$\epsilon_{ijk}$: residual error\

**RQ4:**

$$
DefenderBelievabilityCVP_{ijk} = \beta_0 + \beta_1 \cdot Prompt_i + u_{app(j)} + u_{interaction(jk)} + \epsilon_{ijk}
$$ 

$DefenderBelievabilityCVP_{ijk}$: Defender agent believability concept vector projection score for statement *i* within interaction *k* and application *j*\
$\beta_0$: baseline intercept\
$\beta_1$: fixed effect of target prompt\
$Prompt_i$: the prompt, either vulnerable or misleading, that generated statement *i*\
$u_{app(j)}$: the random intercept for each application *j* (we could possibly add a random slope, but we think this will add uneccessary complexity)\
$u_{interaction(jk)}$: the nested random intercept for each interaction *k* within application *j*\
$\epsilon_{ijk}$: residual error\

**RQ5:**
Repeated measures correlation or linear mixed effect model. Collapse statement level attacker CVP scores to match the amount of defender statements - if we do repeated measure. The linear mixed effect model has not been conceptualized.

**RQ6:**
Repeated measures correlation or linear mixed effect model. Collapse statement level attacker CVP scores to match the amount of defender statements - if we do repeated measure. The linear mixed effect model has not been conceptualized.

**RQ7:**
Generalized linear effect mixed effect models with different link functions depending on the variable:
- Interaction length: poisson
- Cost advantage: no idea
- Detection TPR: binomial
- Test Pass@1: binomial

The above models still has to formulated explicitly. 




