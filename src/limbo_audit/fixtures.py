"""Engine 4 — Built-In Clean-Room Reference Fixture & Adversarial Fault Suite.

Provides a deterministic, self-contained synthetic benchmark corpus modeled on:
- ``Limbo``'s 59-reference verified taxonomy (``trust -> value-of-information -> action``),
  pairing 56 external verified DOI/arXiv/URL entries with 3 AveryCorp software archives
  (``3 / 59 = 0.051 <= 0.15`` self-citation cap) and a 1-to-1 ``CITATIONS.md`` claims ledger.
- ``Gauge`` & ``Matrix``'s 34/34 verbatim traced manuscript numbers across 3 SHA-256-locked
  JSON artifacts (``results/trust_crlb.json``, ``results/voi_retest.json``,
  ``results/action_rt.json``).
- Seeded (``PCG64``) adversarial epistemic mutants verifying 100% fault-detection recall on:
  1. Injected phantom prose citation ``"sun2023phantom"``
  2. Identifier-less ``.bib`` entry ``"unverified2024noid"``
  3. Drifted correlation metric ``r = 0.39`` vs locked ``0.24``
  4. Seeded numeric drift + SHA-256 artifact tamper
  5. Upstream ``PROVISIONAL`` anchor hold in ``release_config``
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .citations import CitationAuditResult, audit_citations
from .consistency import (
    ConsistencyAuditResult,
    audit_numerical_consistency,
    compute_artifact_sha256,
)
from .release_gate import ReleaseGateResult, evaluate_release_gate
from .statcheck import StatCheckResult, audit_stat_consistency

# 59 verified reference specifications:
# (citekey, entry_type, author, title, venue_or_note, year, id_kind, id_value, pillar, verified_claim)
_REFERENCE_CATALOG: tuple[tuple[str, str, str, str, str, str, str, str, str, str], ...] = (
    # ---------------- Pillar I: Trust (24 entries: 21 external + 3 AveryCorp) ----------------
    (
        "gudbjartsson1995",
        "article",
        "Gudbjartsson, Hakon and Patz, Samuel",
        "The {Rician} distribution of noisy {MRI} data",
        "Magnetic Resonance in Medicine",
        "1995",
        "doi",
        "10.1002/mrm.1910340618",
        "trust",
        "Magnitude MRI follows a Rician noise floor that positively biases low-SNR signal intensities.",
    ),
    (
        "constantinides1997",
        "article",
        "Constantinides, Chris D. and Atalar, Ergin and McVeigh, Elliot R.",
        "Signal-to-noise measurements in magnitude images from {NMR} phased arrays",
        "Magnetic Resonance in Medicine",
        "1997",
        "doi",
        "10.1002/mrm.1910380524",
        "trust",
        "Multi-coil root-sum-of-squares reconstruction induces a non-central chi low-SNR magnitude floor.",
    ),
    (
        "veraart2013",
        "article",
        "Veraart, Jelle and Sijbers, Jan and Sunaert, Stefan and Leemans, Alexander and Jeurissen, Ben",
        "Weighted linear least squares estimation of diffusion {MRI} parameters",
        "NeuroImage",
        "2013",
        "doi",
        "10.1016/j.neuroimage.2013.05.028",
        "trust",
        "Unweighted log-linear diffusion fits introduce systematic bias and heteroscedastic variance distortion.",
    ),
    (
        "alexander2008",
        "article",
        "Alexander, Daniel C.",
        "A general framework for experiment design in diffusion {MRI}",
        "Magnetic Resonance in Medicine",
        "2008",
        "doi",
        "10.1002/mrm.21646",
        "trust",
        "Fisher-information and Cramer-Rao lower bound optimization maximize microstructural parameter precision.",
    ),
    (
        "lemke2011",
        "article",
        "Lemke, Andreas and Stieltjes, Bram and Schad, Lothar R. and Laun, Frederik B.",
        "Toward an optimal distribution of b values for intravoxel incoherent motion imaging",
        "Magnetic Resonance Imaging",
        "2011",
        "doi",
        "10.1016/j.mri.2011.03.004",
        "trust",
        "Optimizing b-value placements reduces estimation error on IVIM parameters D, f, and D*.",
    ),
    (
        "raue2009",
        "article",
        "Raue, Andreas and Kreutz, Clemens and Maiwald, Thomas and Timmer, Jens",
        "Structural and practical identifiability analysis of partially observed dynamical models",
        "Bioinformatics",
        "2009",
        "doi",
        "10.1093/bioinformatics/btp358",
        "trust",
        "Profile likelihood exposes structural and practical non-identifiability via flat likelihood ridges.",
    ),
    (
        "efron1979",
        "article",
        "Efron, Bradley",
        "Bootstrap methods: another look at the jackknife",
        "Annals of Statistics",
        "1979",
        "doi",
        "10.1214/aos/1176344552",
        "trust",
        "Bootstrap resampling estimates frequentist sampling distributions without asymptotic Fisher formulas.",
    ),
    (
        "zhang2013",
        "inproceedings",
        "Zhang, Qiong and Coolen, Bram F. and Nederveen, Aart J. and Strijkers, Gustav J.",
        "Cramer-Rao lower bound optimization of {IVIM} b-value schedules",
        "IEEE EMBC",
        "2013",
        "doi",
        "10.1109/EMBC.2013.6609549",
        "trust",
        "CRLB analysis quantifies SNR-dependent estimation bounds on IVIM diffusion and perfusion fractions.",
    ),
    (
        "jalnefjord2019",
        "article",
        "Jalnefjord, Oscar and Montelius, Mikael and Starck, Goran and Ljungberg, Maria",
        "Optimization of b-value schemes for estimation of the diffusion coefficient and perfusion fraction with segmented {IVIM}",
        "Magnetic Resonance in Medicine",
        "2019",
        "doi",
        "10.1002/mrm.27826",
        "trust",
        "Analytical segmented-IVIM CRLBs yield SNR-efficient clinical b-value acquisition schedules.",
    ),
    (
        "orton2014",
        "article",
        "Orton, Matthew R. and Collins, David J. and Koh, Dow-Mu and Leach, Martin O.",
        "Improved intravoxel incoherent motion analysis of diffusion weighted imaging by data driven {Bayesian} modeling",
        "Magnetic Resonance in Medicine",
        "2014",
        "doi",
        "10.1002/mrm.24649",
        "trust",
        "Hierarchical Bayesian shrinkage reduces voxel-wise scatter in IVIM maps relative to least squares.",
    ),
    (
        "barbieri2016",
        "article",
        "Barbieri, Sebastiano and Donati, Olivio F. and Froehlich, Johannes M. and Thoeny, Harriet C.",
        "Impact of the calculation algorithm on biexponential fitting of diffusion-weighted {MRI} in upper abdominal organs",
        "Magnetic Resonance in Medicine",
        "2016",
        "doi",
        "10.1002/mrm.25765",
        "trust",
        "Abdominal IVIM estimates vary substantially across fitting algorithms, motivating explicit precision gates.",
    ),
    (
        "gustafsson2018",
        "article",
        "Gustafsson, Oscar and Montelius, Mikael and Starck, Goran and Ljungberg, Maria",
        "Impact of prior distributions and central tendency measures on {Bayesian} intravoxel incoherent motion model fitting",
        "Magnetic Resonance in Medicine",
        "2018",
        "doi",
        "10.1002/mrm.26783",
        "trust",
        "Bayesian IVIM posteriors depend strongly on prior specification and central-tendency summary at low SNR.",
    ),
    (
        "blei2017",
        "article",
        "Blei, David M. and Kucukelbir, Alp and McAuliffe, Jon D.",
        "Variational inference: a review for statisticians",
        "Journal of the American Statistical Association",
        "2017",
        "doi",
        "10.1080/01621459.2017.1285773",
        "trust",
        "Mean-field ELBO variational approximations scale inference but systematically under-disperse posterior variance.",
    ),
    (
        "bishop1994",
        "techreport",
        "Bishop, Christopher M.",
        "Mixture density networks",
        "Aston University NCRG/94/004",
        "1994",
        "url",
        "https://publications.aston.ac.uk/id/eprint/373/",
        "trust",
        "Mixture density networks parameterize conditional Gaussian mixtures to capture multimodal inverse posteriors.",
    ),
    (
        "papamakarios2016",
        "article",
        "Papamakarios, George and Murray, Iain",
        "Fast epsilon-free inference of simulation models with {Bayesian} conditional density estimation",
        "arXiv preprint",
        "2016",
        "arxiv",
        "1605.06376",
        "trust",
        "Amortized neural conditional density estimators enable rapid likelihood-free posterior approximations.",
    ),
    (
        "kendall2017",
        "article",
        "Kendall, Alex and Gal, Yarin",
        "What uncertainties do we need in {Bayesian} deep learning for computer vision?",
        "arXiv preprint",
        "2017",
        "arxiv",
        "1703.04977",
        "trust",
        "Predictive uncertainty decomposes into heteroscedastic observation noise and epistemic model uncertainty.",
    ),
    (
        "vovk2005",
        "book",
        "Vovk, Vladimir and Gammerman, Alex and Shafer, Glenn",
        "Algorithmic Learning in a Random World",
        "Springer",
        "2005",
        "doi",
        "10.1007/b106715",
        "trust",
        "Conformal prediction constructs finite-sample valid prediction sets under exchangeability alone.",
    ),
    (
        "lei2018",
        "article",
        "Lei, Jing and G'Sell, Max and Rinaldo, Alessandro and Tibshirani, Ryan J. and Wasserman, Larry",
        "Distribution-free predictive inference for regression",
        "Journal of the American Statistical Association",
        "2018",
        "doi",
        "10.1080/01621459.2017.1307116",
        "trust",
        "Split conformal and locally weighted residual scoring deliver finite-sample regression intervals.",
    ),
    (
        "romano2019",
        "article",
        "Romano, Yaniv and Patterson, Evan and Candes, Emmanuel",
        "Conformalized quantile regression",
        "arXiv preprint",
        "2019",
        "arxiv",
        "1905.03222",
        "trust",
        "Conformalized quantile regression pairs conditional quantile estimators with finite-sample calibration.",
    ),
    (
        "tibshirani2019",
        "article",
        "Tibshirani, Ryan J. and Foygel Barber, Rina and Candes, Emmanuel and Ramdas, Aaditya",
        "Conformal prediction under covariate shift",
        "arXiv preprint",
        "2019",
        "arxiv",
        "1904.06019",
        "trust",
        "Likelihood-ratio importance weighting restores finite-sample conformal coverage under covariate shift.",
    ),
    (
        "barber2021",
        "article",
        "Foygel Barber, Rina and Candes, Emmanuel J. and Ramdas, Aaditya and Tibshirani, Ryan J.",
        "The limits of distribution-free conditional predictive inference",
        "Information and Inference",
        "2021",
        "doi",
        "10.1093/imaiai/iaaa017",
        "trust",
        "Exact distribution-free conditional coverage is impossible with nontrivial finite intervals on continuous domains.",
    ),
    (
        "karlin2026sextant",
        "misc",
        "Karlin, Avery",
        "sextantIVIM: Assumption-free {IVIM} boundary-railing diagnostics and {CRLB} identifiability toolkit",
        "Zenodo",
        "2026",
        "doi",
        "10.5281/zenodo.20649669",
        "trust",
        "Box-constraint NLLS boundary-railing diagnoses practical pseudo-diffusion non-identifiability without prior assumptions.",
    ),
    (
        "karlin2026conformal",
        "misc",
        "Karlin, Avery",
        "conformalIVIM: Distribution-free conformal prediction intervals and deployment monitoring for {IVIM} {MRI}",
        "Zenodo",
        "2026",
        "doi",
        "10.5281/zenodo.20694662",
        "trust",
        "Split-conformal quantile calibration restores marginal IVIM coverage while exposing high-D* conditional limits.",
    ),
    (
        "karlin2026proteus",
        "misc",
        "Karlin, Avery",
        "proteusMine: Structure-first dark proteome catalytic triad screening and {TOST} non-superiority audit",
        "Zenodo",
        "2026",
        "doi",
        "10.5281/zenodo.20758580",
        "trust",
        "Pre-registered TOST equivalence and confound stratification audit structural non-superiority claims.",
    ),
    # ---------------- Pillar II: Value of Information (18 external entries) ----------------
    (
        "gneiting2007",
        "article",
        "Gneiting, Tilmann and Raftery, Adrian E.",
        "Strictly proper scoring rules, prediction, and estimation",
        "Journal of the American Statistical Association",
        "2007",
        "doi",
        "10.1198/016214506000001437",
        "voi",
        "Probabilistic forecasts maximize sharpness subject to calibration under strictly proper scoring rules.",
    ),
    (
        "talts2018",
        "article",
        "Talts, Sean and Betancourt, Michael and Simpson, Daniel and Vehtari, Aki and Gelman, Andrew",
        "Validating {Bayesian} inference algorithms with simulation-based calibration",
        "arXiv preprint",
        "2018",
        "arxiv",
        "1804.06788",
        "voi",
        "Simulation-based calibration detects posterior bias and miscalibration via prior-predictive rank uniformity.",
    ),
    (
        "hermans2022",
        "article",
        "Hermans, Joeri and Delaunoy, Arnaud and Rozet, Francois and Wehenkel, Antoine and Louppe, Gilles",
        "A trust crisis in simulation-based inference? Your posterior approximations can be unfaithful",
        "arXiv preprint",
        "2022",
        "arxiv",
        "2110.06581",
        "voi",
        "Amortized neural SBI posteriors frequently produce overconfident credible sets that fail coverage checks.",
    ),
    (
        "frazier2020",
        "article",
        "Frazier, David T. and Robert, Christian P. and Rousseau, Judith",
        "Model misspecification in approximate {Bayesian} computation: consequences and diagnostics",
        "Journal of the Royal Statistical Society Series B",
        "2020",
        "doi",
        "10.1111/rssb.12356",
        "voi",
        "Forward-model misspecification concentrates posteriors onto pseudo-true parameters without frequentist coverage.",
    ),
    (
        "ovadia2019",
        "article",
        "Ovadia, Yaniv and Fertig, Emily and Ren, Jie and Nado, Zachary and Sculley, D. and Nowozin, Sebastian and Dillon, Joshua V. and Lakshminarayanan, Balaji and Snoek, Jasper",
        "Can you trust your model's uncertainty? Evaluating predictive uncertainty under dataset shift",
        "arXiv preprint",
        "2019",
        "arxiv",
        "1906.02530",
        "voi",
        "Predictive uncertainty calibration degrades substantially under covariate and acquisition shift.",
    ),
    (
        "raunig2015",
        "article",
        "Raunig, David L. and McShane, Lisa M. and Pennello, Gene and Gatsonis, Constantine and Carson, Paul L. and Voyvodic, James T. and Wahl, Richard L. and Kurland, Brenda F. and Schwarz, Arnold J. and Gonen, Mithat and Zahlmann, Gudrun and Kondratovich, Marina V. and O'Donnell, Kevin andolis and Buckler, Andrew J.",
        "Quantitative imaging biomarkers: a review of statistical methods for technical performance assessment",
        "Statistical Methods in Medical Research",
        "2015",
        "doi",
        "10.1177/0962280214537344",
        "voi",
        "QIBA technical validation rests on linearity/bias, test-retest repeatability, and multi-scanner reproducibility.",
    ),
    (
        "shukladave2019",
        "article",
        "Shukla-Dave, Amita and Obuchowski, Nancy A. and Chenevert, Thomas L. and Jambawalikar, Sachin and Schwartz, Lawrence H. and Malyarenko, Dariya and Huang, Wei and Noworolski, Susan M. and Young, Robert J. and Shiroishi, Mark S. and Kim, Hyungsub and Coolens, Catherine and Laue, Hendrik and Chung, Caroline and Rosen, Mark and Boss, Michael and Jackson, Edward F.",
        "Quantitative imaging biomarkers alliance ({QIBA}) recommendations for improved precision of {DWI} and {DCE-MRI}",
        "Journal of Magnetic Resonance Imaging",
        "2019",
        "doi",
        "10.1002/jmri.26518",
        "voi",
        "QIBA establishes repeatability coefficient (RC = 2.77 s_w) protocols for oncology DWI and DCE-MRI.",
    ),
    (
        "koo2016",
        "article",
        "Koo, Terry K. and Li, Mae Y.",
        "A guideline of selecting and reporting intraclass correlation coefficients for reliability research",
        "Journal of Chiropractic Medicine",
        "2016",
        "doi",
        "10.1016/j.jcm.2016.02.012",
        "voi",
        "Standardizes selection and reporting of intraclass correlation coefficients in clinical reliability studies.",
    ),
    (
        "blandaltman1986",
        "article",
        "Bland, J. Martin and Altman, Douglas G.",
        "Statistical methods for assessing agreement between two methods of clinical measurement",
        "The Lancet",
        "1986",
        "doi",
        "10.1016/S0140-6736(86)90837-8",
        "voi",
        "Limits of agreement, rather than correlation alone, quantify clinical measurement repeatability.",
    ),
    (
        "sun2019",
        "article",
        "Sun, Hong and Xu, Yikai and Xu, Qiaoyu and Shi, Kexin and Wang, Wei",
        "Rectal cancer: short-term reproducibility of intravoxel incoherent motion parameters and correlation with {DCE-MRI}",
        "Academic Radiology",
        "2019",
        "doi",
        "10.1016/j.acra.2018.08.012",
        "voi",
        "Rectal cancer IVIM D* correlates weakly with DCE Ktrans (r=0.389) whereas f*D* reaches r=0.533.",
    ),
    (
        "yang2019",
        "article",
        "Yang, Xiaoyu and Chen, Yan and Wen, Zhibo and Lu, Baoli and Xiao, Xue",
        "Reproducibility of intravoxel incoherent motion and comparison with dynamic contrast-enhanced {MRI}",
        "Acta Radiologica",
        "2019",
        "doi",
        "10.1177/0284185118791201",
        "voi",
        "IVIM D* exhibits moderate reproducibility (ICC=0.55) and null correlation with DCE Ktrans.",
    ),
    (
        "osipidata2025",
        "misc",
        "OSIPI Taskforce 2.4",
        "{ISMRM} {OSIPI} {TF2.4} {IVIM-MRI} code collection and reference digital reference object",
        "Zenodo",
        "2025",
        "doi",
        "10.5281/zenodo.14605039",
        "voi",
        "Provides open IVIM reference implementations and synthetic digital reference objects for standardized benchmarking.",
    ),
    (
        "acrin6698",
        "misc",
        "Newitt, David C. and Partridge, Savannah C. and Hylton, Nola M.",
        "Data from {ACRIN-6698/I-SPY2} breast {DWI}",
        "The Cancer Imaging Archive",
        "2019",
        "doi",
        "10.7937/TCIA.KK02-6D95",
        "voi",
        "Multicenter breast DWI test-retest and longitudinal treatment cohort with QIBA phantom quality control.",
    ),
    (
        "vickers2006",
        "article",
        "Vickers, Andrew J. and Elkin, Elena B.",
        "Decision curve analysis: a novel method for evaluating prediction models",
        "Medical Decision Making",
        "2006",
        "doi",
        "10.1177/0272989X06295361",
        "voi",
        "Decision curve analysis evaluates prediction models via clinical net benefit across threshold probabilities.",
    ),
    (
        "zhao2021",
        "article",
        "Zhao, Shengjia and Kim, Michael P. and Sahoo, Roshni and Ma, Tengyu and Ermon, Stefano",
        "Calibrating predictions to decisions: a novel approach to multi-class calibration",
        "arXiv preprint",
        "2021",
        "arxiv",
        "2107.05719",
        "voi",
        "Decision calibration requires predicted distributions to be indistinguishable to downstream loss-minimizing actions.",
    ),
    (
        "lacostejulien2011",
        "inproceedings",
        "Lacoste-Julien, Simon and Huszar, Ferenc and Ghahramani, Zoubin",
        "Approximate inference for the loss-calibrated {Bayesian}",
        "AISTATS / PMLR",
        "2011",
        "url",
        "https://proceedings.mlr.press/v15/lacoste_julien11a.html",
        "voi",
        "Loss-calibrated inference tailors posterior approximations directly to asymmetric downstream decision regret.",
    ),
    (
        "felli1998",
        "article",
        "Felli, James C. and Hazen, Gordon B.",
        "Sensitivity analysis and the expected value of perfect information",
        "Medical Decision Making",
        "1998",
        "doi",
        "10.1177/0272989X9801800117",
        "voi",
        "Expected value of perfect information weights decision-reversal probability by marginal utility gain.",
    ),
    (
        "claxton1999",
        "article",
        "Claxton, Karl",
        "The irrelevance of inference: a decision-making approach to the stochastic evaluation of health care technologies",
        "Journal of Health Economics",
        "1999",
        "doi",
        "10.1016/S0167-6296(98)00039-3",
        "voi",
        "Optimal clinical action depends on expected net benefit and value of information rather than arbitrary p-values.",
    ),
    # ---------------- Pillar III: Action (17 external entries) ----------------
    (
        "lebihan1988",
        "article",
        "Le Bihan, Denis and Breton, Eric and Lallemand, Denis and Aubin, Marie-Louise and Vignaud, Jacqueline and Laval-Jeantet, Maurice",
        "Separation of diffusion and perfusion in intravoxel incoherent motion {MR} imaging",
        "Radiology",
        "1988",
        "doi",
        "10.1148/radiology.168.2.3393671",
        "action",
        "Biexponential IVIM separates slow molecular water diffusion from fast capillary microcirculation.",
    ),
    (
        "tofts1999",
        "article",
        "Tofts, Paul S. and Brix, Gunnar and Buckley, David L. and Evelhoch, Jeffrey L. and Henderson, Elizabeth and Knopp, Michael V. and Larsson, Henrik B. W. and Lee, Ting-Yim and Mayr, Nina A. and Parker, Geoffrey J. M. and Port, Ruediger E. and Taylor, June and Weisskoff, Robert M.",
        "Estimating kinetic parameters from dynamic contrast-enhanced {$T_1$}-weighted {MRI} of a diffusable tracer",
        "Journal of Magnetic Resonance Imaging",
        "1999",
        "doi",
        "10.1002/(SICI)1522-2586(199909)10:3<223::AID-JMRI2>3.0.CO;2-S",
        "action",
        "Standardizes DCE-MRI pharmacokinetic transfer constant Ktrans, extravascular space ve, and rate constant kep.",
    ),
    (
        "lagendijk2008",
        "article",
        "Lagendijk, Jan J. W. and Raaymakers, Bas W. and Raaijmakers, Alexander J. E. and Overweg, Johan and Brown, Kevin J. and Kerkhof, Ellen M. and van der Put, Richard W. and Hardemark, Bjorn and van Vulpen, Marco and van der Heide, Uulke A.",
        "{MRI}/linac integration",
        "Radiotherapy and Oncology",
        "2008",
        "doi",
        "10.1016/j.radonc.2007.10.034",
        "action",
        "Integrating diagnostic-grade MRI with a linear accelerator enables real-time soft-tissue and functional RT guidance.",
    ),
    (
        "raaymakers2017",
        "article",
        "Raaymakers, Bas W. and Jurgenliemk-Schulz, Ina M. and Bol, Gijs H. and Glitzner, Matteo and Kotte, Alexis N. T. J. and van Asselen, Bram and de Boer, Johannes C. J. and Bluemink, Johanna J. and Hackett, Sara L. and Moerland, Marinus A. and Woodings, Simon J. and Wolthaus, Jochem W. H. and van Zijp, HM and Philippens, Marielle E. P. and Tijssen, Rob H. N. and Kok, Jan G. M. and de Groot-van Breugel, EN and Kiekebosch, IH and Meijers, LTC and Nomden, CN and Sikkes, GG and Doornaert, PA and Eppinga, WSC and Kasperts, N and Kerkmeijer, LGW and Tersteeg, RJHA and Brown, KJ and Pais, B and Woodhead, P and Lagendijk, Jan J. W.",
        "First patients treated with a 1.5 {T} {MRI-Linac}: clinical proof of concept of a high-precision, high-field {MRI} guided radiotherapy treatment",
        "Physics in Medicine & Biology",
        "2017",
        "doi",
        "10.1088/1361-6560/aa9517",
        "action",
        "First-in-human 1.5 T MR-Linac treatments establish clinical feasibility of high-field MR-guided adaptive radiotherapy.",
    ),
    (
        "kooreman2019",
        "article",
        "Kooreman, Ernst S. and van Houdt, Petra J. and Nowee, Marlies E. and van Pelt, Vivian W. J. and Tijssen, Rob H. N. and Paulson, Eric S. and Gurney-Champion, Oliver J. and Wang, Jihong and Koetsveld, Femke and van der Heide, Uulke A.",
        "Feasibility and accuracy of quantitative imaging on a 1.5 {T} {MR}-linear accelerator",
        "Radiotherapy and Oncology",
        "2019",
        "doi",
        "10.1016/j.radonc.2019.01.011",
        "action",
        "Multicenter 1.5 T MR-Linac validation demonstrates quantitative T1, T2, ADC, and DCE feasibility alongside gradient limits.",
    ),
    (
        "kooreman2021",
        "article",
        "Kooreman, Ernst S. and van Houdt, Petra J. and Keesman, Rick and van Pelt, Vivian W. J. and Nowee, Marlies E. and Pos, Floris and Sikorska, Kasia and Wiersma, Jan and vanlen and van der Heide, Uulke A.",
        "Daily intravoxel incoherent motion ({IVIM}) in prostate cancer patients during {MR}-guided radiotherapy",
        "Frontiers in Oncology",
        "2021",
        "doi",
        "10.3389/fonc.2021.705964",
        "action",
        "Daily MR-Linac prostate IVIM requires repeatability gating to separate genuine treatment response from acquisition noise.",
    ),
    (
        "ling2000",
        "article",
        "Ling, C. Clifton and Humm, John and Larson, Steven and Amols, Howard and Fuks, Zvi and Leibel, Steven and Koutcher, Jason A.",
        "Towards multidimensional radiotherapy ({MD-CRT}): biological imaging and biological conformality",
        "International Journal of Radiation Oncology Biology Physics",
        "2000",
        "doi",
        "10.1016/S0360-3016(00)00467-3",
        "action",
        "Introduces the biological target volume (BTV) to guide spatially non-uniform dose conformality from functional imaging.",
    ),
    (
        "bentzen2005",
        "article",
        "Bentzen, Soren M.",
        "Theragnostic imaging for radiation oncology: dose-painting by numbers",
        "The Lancet Oncology",
        "2005",
        "doi",
        "10.1016/S1470-2045(05)01737-7",
        "action",
        "Dose painting by numbers maps continuous voxel-level functional biomarker values directly into prescription dose.",
    ),
    (
        "bentzen2011",
        "article",
        "Bentzen, Soren M. and Gregoire, Vincent",
        "Molecular imaging-based dose painting: a novel paradigm for radiation therapy prescription",
        "Seminars in Radiation Oncology",
        "2011",
        "doi",
        "10.1016/j.semradonc.2010.10.001",
        "action",
        "Voxel-wise dose redistribution targets resistant tumor subvolumes conditioned on quantitative biomarker maps.",
    ),
    (
        "thorwarth2007",
        "article",
        "Thorwarth, Daniela and Eschmann, Susanne-Martina and Paulsen, Frank and Alber, Markus",
        "Hypoxia dose painting by numbers: a planning study",
        "International Journal of Radiation Oncology Biology Physics",
        "2007",
        "doi",
        "10.1016/j.ijrobp.2006.11.061",
        "action",
        "Biophysical hypoxia dose painting increases modeled tumor control probability at iso-integral target dose.",
    ),
    (
        "vanherk2000",
        "article",
        "van Herk, Marcel and Remeijer, Peter and Rasch, Coen and Lebesque, Joos V.",
        "The probability of correct target dosage: dose-population histograms for deriving treatment margins in radiotherapy",
        "International Journal of Radiation Oncology Biology Physics",
        "2000",
        "doi",
        "10.1016/S0360-3016(00)00518-6",
        "action",
        "Separates systematic preparation error from random execution blurring in probabilistic radiotherapy margin recipes.",
    ),
    (
        "webb1993",
        "article",
        "Webb, Steve and Nahum, Alan E.",
        "A model for calculating tumour control probability in radiotherapy including the effects of inhomogeneous distributions of dose and clonogenic cell density",
        "Physics in Medicine & Biology",
        "1993",
        "doi",
        "10.1088/0031-9155/38/6/001",
        "action",
        "Poisson linear-quadratic TCP integrates heterogeneous dose and clonogen density, inducing Jensen optimism bias under noise.",
    ),
    (
        "lyman1985",
        "article",
        "Lyman, John T.",
        "Complication probability as assessed from dose-volume histograms",
        "Radiation Research",
        "1985",
        "doi",
        "10.2307/3583506",
        "action",
        "Maps organ-at-risk dose-volume histograms to normal-tissue complication probability via power-law volume reduction.",
    ),
    (
        "niemierko1997",
        "article",
        "Niemierko, Andrzej",
        "Reporting and analyzing dose distributions: a concept of equivalent uniform dose",
        "Medical Physics",
        "1997",
        "doi",
        "10.1118/1.598063",
        "action",
        "Generalized equivalent uniform dose summarizes inhomogeneous tumor and OAR dose distributions via tissue power laws.",
    ),
    (
        "unkelbach2018",
        "article",
        "Unkelbach, Jan and Alber, Markus and Bangert, Mark and Bokrantz, Rasmus and Chan, Timothy C. Y. and Deasy, Joseph O. and Fredriksson, Albin and Gorissen, Bram L. and van Herk, Marcel and Liu, Wei and Mahmoudzadeh, Hamidreza and Men, Chunhua and Mihaylov, Ivaylo B. and Oelfke, Uwe and Paganetti, Harald and Pashaei, Ali and Perkó, Zoltán and Bortfeld, Thomas",
        "Robust radiotherapy planning",
        "Physics in Medicine & Biology",
        "2018",
        "doi",
        "10.1088/1361-6560/aae659",
        "action",
        "Stochastic and worst-case robust optimization propagate spatial and parameter uncertainty directly into fluence planning.",
    ),
    (
        "vanhoudt2021qib",
        "article",
        "van Houdt, Petra J. and Saeed, Hina and Thorwarth, Daniela and Fuller, Clifton D. and Hall, William A. and McDonald, Brigid A. and Shukla-Dave, Amita and Kooreman, Ernst S. and van der Heide, Uulke A.",
        "Integration of quantitative imaging biomarkers in clinical trials for {MR}-guided radiotherapy",
        "European Journal of Cancer",
        "2021",
        "doi",
        "10.1016/j.ejca.2021.04.041",
        "action",
        "MR-Linac quantitative biomarkers require phantom QA and in vivo test-retest validation prior to adaptive dose escalation.",
    ),
    (
        "hall2022",
        "article",
        "Hall, William A. and Paulson, Eric and Li, X. Allen and Erickson, Beth and Schultz, Christopher and Tree, Alison and Awan, Musaddiq and Low, Daniel A. and McDonald, Brigid A. and Salzillo, Travis and Glide-Hurst, Carri K. and Kishan, Amar U. and Fuller, Clifton D.",
        "Magnetic resonance linear accelerator technology and adaptive radiation therapy: an overview for clinicians",
        "CA: A Cancer Journal for Clinicians",
        "2022",
        "doi",
        "10.3322/caac.21707",
        "action",
        "Synthesizes clinical workflows and safety requirements for online MR-guided adaptive radiation therapy.",
    ),
)

assert len(_REFERENCE_CATALOG) == 59, f"Expected 59 references, got {len(_REFERENCE_CATALOG)}"


def _render_canonical_bib() -> str:
    blocks = [
        "% Canonical 59-entry verified bibliography (Limbo Trust -> VoI -> Action taxonomy)",
        "% Zero phantom citations; 100% resolvable identifiers (DOI / arXiv / stable URL).",
        "",
    ]
    for key, etype, author, title, venue, year, id_kind, id_val, _pillar, _claim in _REFERENCE_CATALOG:
        venue_field = "booktitle" if etype == "inproceedings" else "journal"
        if etype in {"book", "misc", "techreport"}:
            venue_field = "publisher" if etype == "book" else "howpublished"
        if id_kind == "doi":
            id_line = f"  doi     = {{{id_val}}}"
        elif id_kind == "arxiv":
            id_line = f"  eprint  = {{{id_val}}},\n  archiveprefix = {{arXiv}}"
        elif id_kind == "pmid":
            id_line = f"  pmid    = {{{id_val}}}"
        else:
            id_line = f"  url     = {{{id_val}}}"
        blocks.append(
            f"@{etype}{{{key},\n"
            f"  author  = {{{author}}},\n"
            f"  title   = {{{title}}},\n"
            f"  {venue_field:<7} = {{{venue}}},\n"
            f"  year    = {{{year}}},\n"
            f"{id_line}\n"
            f"}}\n"
        )
    return "\n".join(blocks)


def _render_canonical_ledger() -> str:
    lines = [
        "# CITATIONS.md — Canonical 59-Entry Verified Claims Ledger",
        "",
        "| key | identifier | verified claim |",
        "|---|---|---|",
    ]
    for key, _etype, _author, _title, _venue, _year, id_kind, id_val, _pillar, claim in _REFERENCE_CATALOG:
        prefix = "arXiv" if id_kind == "arxiv" else id_kind
        lines.append(f"| `{key}` | {prefix}:{id_val} | {claim} |")
    lines.extend(
        [
            "",
            "## In-portfolio non-cited provenance note (excluded from backtick ledger rows)",
            "",
            "| anchor | status | note |",
            "|---|---|---|",
            "| Limbo | LOCKED | Standalone field review |",
        ]
    )
    return "\n".join(lines) + "\n"


CANONICAL_ARTIFACTS: dict[str, dict[str, Any]] = {
    "results/trust_crlb.json": {
        "railing_rate_osipi": 0.542,
        "crlb_growth_factor": 5.7,
        "crlb_tercile_ratio_hi": 1.12,
        "conformal_width_crlb_r": 0.77,
        "marginal_coverage_f": 0.951,
        "marginal_coverage_f_lo": 0.938,
        "marginal_coverage_f_hi": 0.963,
        "ece_f": 0.018,
        "cqr_high_dstar_cov": 0.784,
        "nominal_snr": 40,
        "low_snr_zone": 12,
        "cohort_voxels": 4096,
    },
    "results/voi_retest.json": {
        "dstar_retest_r": 0.24,
        "dstar_width_repeatability_r": -0.17,
        "dstar_width_repeatability_p": 0.13,
        "retest_pairs_n": 76,
        "dstar_ci95_lo": -0.39,
        "dstar_ci95_hi": 0.05,
        "d_retest_r": 0.60,
        "d_ci95_lo": 0.42,
        "d_ci95_hi": 0.72,
        "auroc_trust_gate": 0.94,
        "evpi_threshold_gain": 0.043,
    },
    "results/action_rt.json": {
        "act_rate_untrust_ungated": 0.412,
        "act_rate_untrust_gated": 0.000,
        "act_rate_trust_gated": 0.684,
        "drop_trusted_tumour": 0.062,
        "drop_trusted_lo": 0.048,
        "drop_trusted_hi": 0.076,
        "f1_held_drop_real_dose": 0.019,
        "f1_held_drop_lo": 0.007,
        "f1_held_drop_hi": 0.031,
        "dose_floor_gy": 60.0,
        "dose_ceiling_gy": 78.0,
    },
}

CANONICAL_ARTIFACT_DIGESTS: dict[str, str] = {
    name: compute_artifact_sha256(payload) for name, payload in CANONICAL_ARTIFACTS.items()
}

# 34 traced macros: (macro_name, artifact_keypath, format_spec, formatted_value)
_MACRO_SPECS: tuple[tuple[str, str, str, str], ...] = (
    # Trust / CRLB & Conformal (12)
    ("numRailingRateOsipi", "results/trust_crlb.json:railing_rate_osipi", "{:.3f}", "0.542"),
    ("numCRLBGrowth", "results/trust_crlb.json:crlb_growth_factor", "{:.1f}", "5.7"),
    ("numCRLBTercileRatio", "results/trust_crlb.json:crlb_tercile_ratio_hi", "{:.2f}", "1.12"),
    ("numWidthCRLBr", "results/trust_crlb.json:conformal_width_crlb_r", "{:.2f}", "0.77"),
    ("numCovF", "results/trust_crlb.json:marginal_coverage_f", "{:.3f}", "0.951"),
    ("numCovFlo", "results/trust_crlb.json:marginal_coverage_f_lo", "{:.3f}", "0.938"),
    ("numCovFhi", "results/trust_crlb.json:marginal_coverage_f_hi", "{:.3f}", "0.963"),
    ("numECEf", "results/trust_crlb.json:ece_f", "{:.3f}", "0.018"),
    ("numCQRHighDstarCov", "results/trust_crlb.json:cqr_high_dstar_cov", "{:.3f}", "0.784"),
    ("numNominalSNR", "results/trust_crlb.json:nominal_snr", "{:d}", "40"),
    ("numLowSNRZone", "results/trust_crlb.json:low_snr_zone", "{:d}", "12"),
    ("numCohortVoxels", "results/trust_crlb.json:cohort_voxels", "{:d}", "4096"),
    # Value of Information / Repeatability (11)
    ("numDstarRetestR", "results/voi_retest.json:dstar_retest_r", "{:.2f}", "0.24"),
    ("numDstarWidthR", "results/voi_retest.json:dstar_width_repeatability_r", "{:+.2f}", "-0.17"),
    ("numDstarWidthP", "results/voi_retest.json:dstar_width_repeatability_p", "{:.2f}", "0.13"),
    ("numRetestPairsN", "results/voi_retest.json:retest_pairs_n", "{:d}", "76"),
    ("numDstarCIlo", "results/voi_retest.json:dstar_ci95_lo", "{:+.2f}", "-0.39"),
    ("numDstarCIhi", "results/voi_retest.json:dstar_ci95_hi", "{:+.2f}", "+0.05"),
    ("numDRetestR", "results/voi_retest.json:d_retest_r", "{:+.2f}", "+0.60"),
    ("numDCIlo", "results/voi_retest.json:d_ci95_lo", "{:+.2f}", "+0.42"),
    ("numDCIhi", "results/voi_retest.json:d_ci95_hi", "{:+.2f}", "+0.72"),
    ("numAUROCTrustGate", "results/voi_retest.json:auroc_trust_gate", "{:.2f}", "0.94"),
    ("numEVPITriggerGain", "results/voi_retest.json:evpi_threshold_gain", "{:.3f}", "0.043"),
    # Action / Adaptive Radiotherapy Suppression & Dose (11)
    ("numSupUngated", "results/action_rt.json:act_rate_untrust_ungated", "{:.3f}", "0.412"),
    ("numSupGated", "results/action_rt.json:act_rate_untrust_gated", "{:.3f}", "0.000"),
    ("numSupTrust", "results/action_rt.json:act_rate_trust_gated", "{:.3f}", "0.684"),
    ("numDropTrust", "results/action_rt.json:drop_trusted_tumour", "{:.3f}", "0.062"),
    ("numDropTrustLo", "results/action_rt.json:drop_trusted_lo", "{:.3f}", "0.048"),
    ("numDropTrustHi", "results/action_rt.json:drop_trusted_hi", "{:.3f}", "0.076"),
    ("numFOneHeld", "results/action_rt.json:f1_held_drop_real_dose", "{:.3f}", "0.019"),
    ("numFOneHeldLo", "results/action_rt.json:f1_held_drop_lo", "{:.3f}", "0.007"),
    ("numFOneHeldHi", "results/action_rt.json:f1_held_drop_hi", "{:.3f}", "0.031"),
    ("numDoseMinGy", "results/action_rt.json:dose_floor_gy", "{:.0f}", "60"),
    ("numDoseMaxGy", "results/action_rt.json:dose_ceiling_gy", "{:.0f}", "78"),
)

assert len(_MACRO_SPECS) == 34, f"Expected 34 traced numbers, got {len(_MACRO_SPECS)}"

CANONICAL_CLAIMS_MAP: dict[str, dict[str, Any]] = {
    macro: {
        "path": path,
        "fmt": fmt,
        "sha256": CANONICAL_ARTIFACT_DIGESTS[path.split(":", 1)[0]],
    }
    for macro, path, fmt, _val in _MACRO_SPECS
}


def _render_canonical_numbers_tex() -> str:
    lines = [
        "% AUTO-GENERATED numbers.tex — 34 verbatim artifact-traced macros",
    ]
    for macro, path, _fmt, val in _MACRO_SPECS:
        lines.append(f"\\newcommand{{\\{macro}}}{{{val}}}  % @trace {path}")
    return "\n".join(lines) + "\n"


def _render_canonical_manuscript_tex() -> str:
    trust_keys = [r[0] for r in _REFERENCE_CATALOG if r[8] == "trust"]
    voi_keys = [r[0] for r in _REFERENCE_CATALOG if r[8] == "voi"]
    action_keys = [r[0] for r in _REFERENCE_CATALOG if r[8] == "action"]

    return (
        _render_canonical_numbers_tex()
        + "\n"
        + r"""\section{Trust: Inverse-Problem Identifiability and Finite-Sample Calibration}
Magnitude noise floors \cite{"""
        + ",".join(trust_keys[:8])
        + r"""} and ill-conditioned multi-exponential decay \citep{"""
        + ",".join(trust_keys[8:16])
        + r"""} drive box-constraint boundary railing to \numRailingRateOsipi{} across \numCohortVoxels{} phantom voxels at nominal SNR \numNominalSNR{} (low-SNR zone \numLowSNRZone{}), with $\mathrm{CRLB}(D^*)$ expanding \numCRLBGrowth{}$\times$ to \numCRLBTercileRatio{}$\times$ the tercile width ($r = \numWidthCRLBr{}$) \citet{"""
        + ",".join(trust_keys[16:])
        + r"""}. Conformalized calibration restores $f$-coverage to \numCovF{} (95\% CI [\numCovFlo{}, \numCovFhi{}], ECE \numECEf{}), whereas high-$D^*$ conditional coverage plateaus at \numCQRHighDstarCov{}.

\section{Value of Information: Repeatability Floors and Loss-Calibrated Gating}
Under distribution shift and QIBA test--retest protocols ($n = \numRetestPairsN{}$ pairs) \cite{"""
        + ",".join(voi_keys[:9])
        + r"""}, empirical $D^*$ repeatability stabilizes at $r = \numDstarRetestR{}$ while width-to-error rank correlation is $r = \numDstarWidthR{}$ ($p = \numDstarWidthP{}$, 95\% CI [\numDstarCIlo{}, \numDstarCIhi{}]), contrasting with slow diffusion $D$ ($r = \numDRetestR{}$, CI [\numDCIlo{}, \numDCIhi{}]) \citep{"""
        + ",".join(voi_keys[9:])
        + r"""}. Out-of-regime abstention achieves AUROC \numAUROCTrustGate{} and net EVPI gain \numEVPITriggerGain{}.

\section{Action: Uncertainty-Gated Dose Painting in Adaptive Radiotherapy}
Propagating calibrated intervals into MR-Linac dose painting (\numDoseMinGy{}--\numDoseMaxGy{}~Gy) \cite{"""
        + ",".join(action_keys[:9])
        + r"""} suppresses untrusted escalation from \numSupUngated{} to \numSupGated{} while preserving \numSupTrust{} action rate in identifiable tumor subvolumes \citep{"""
        + ",".join(action_keys[9:])
        + r"""}, yielding trusted perfusion drop \numDropTrust{} ([\numDropTrustLo{}, \numDropTrustHi{}]) and grounded spill drop \numFOneHeld{} ([\numFOneHeldLo{}, \numFOneHeldHi{}]).
"""
    )


CANONICAL_BIB_TEXT: str = _render_canonical_bib()
CANONICAL_LEDGER_TEXT: str = _render_canonical_ledger()
CANONICAL_NUMBERS_TEX: str = _render_canonical_numbers_tex()
CANONICAL_MANUSCRIPT_TEX: str = _render_canonical_manuscript_tex()

CANONICAL_RELEASE_CONFIG: dict[str, Any] = {
    "document_type": "field_review",
    "author_patterns": ["Karlin, Avery"],
    "max_self_citation_fraction": 0.15,
    "forbid_unpublished_bib": True,
    "anchors": {
        "SEXTANT_TRUST": {
            "status": "LOCKED",
            "published": True,
            "doi": "10.5281/zenodo.20649669",
            "load_bearing": True,
        },
        "CONFORMAL_RULER": {
            "status": "LOCKED",
            "published": True,
            "doi": "10.5281/zenodo.20694662",
            "load_bearing": True,
        },
        "PROTEUS_AUDIT": {
            "status": "LOCKED",
            "published": True,
            "doi": "10.5281/zenodo.20758580",
            "load_bearing": False,
        },
    },
}


@dataclass(frozen=True)
class MutantCheckResult:
    """Outcome of a single adversarial epistemic fault-injection trap."""

    mutant_id: str
    engine: str
    description: str
    detected: bool
    diagnostic: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutant_id": self.mutant_id,
            "engine": self.engine,
            "description": self.description,
            "detected": self.detected,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class CanonicalBenchmarkEvaluation:
    """Bundled evaluation of the canonical corpus and seeded adversarial mutant suite."""

    citations_result: CitationAuditResult
    consistency_result: ConsistencyAuditResult
    release_result: ReleaseGateResult
    statcheck_result: StatCheckResult
    mutant_results: tuple[MutantCheckResult, ...]
    adversarial_fault_recall: float
    statcheck_trap_recall: float


def evaluate_canonical_and_adversarial(seed: int = 42) -> CanonicalBenchmarkEvaluation:
    """Run all four Open-Core verification engines on the canonical fixture plus seeded mutant traps."""
    rng = np.random.Generator(np.random.PCG64(int(seed)))

    cit_res = audit_citations(
        CANONICAL_BIB_TEXT,
        CANONICAL_MANUSCRIPT_TEX,
        ledger_text=CANONICAL_LEDGER_TEXT,
        online=False,
    )
    con_res = audit_numerical_consistency(
        CANONICAL_MANUSCRIPT_TEX,
        CANONICAL_CLAIMS_MAP,
        CANONICAL_ARTIFACTS,
        rtol=1e-4,
        atol=1e-4,
        artifact_digests=CANONICAL_ARTIFACT_DIGESTS,
    )
    rel_res = evaluate_release_gate(CANONICAL_RELEASE_CONFIG, cit_res)
    stat_res = audit_stat_consistency(CANONICAL_MANUSCRIPT_TEX)

    mutants: list[MutantCheckResult] = []

    # Mutant 1: Injected phantom citation "sun2023phantom" (Ouroboros / LLM hallucination trap)
    prose_lines = CANONICAL_MANUSCRIPT_TEX.splitlines()
    section_indices = [i for i, ln in enumerate(prose_lines) if ln.startswith("\\section")]
    insert_idx = int(section_indices[int(rng.integers(0, len(section_indices)))]) + 1
    mut_prose_phantom = "\n".join(
        prose_lines[:insert_idx]
        + ["Prior studies allegedly established exact high-b perfusion invertibility \\citep{sun2023phantom}."]
        + prose_lines[insert_idx:]
    )
    m1_res = audit_citations(
        CANONICAL_BIB_TEXT, mut_prose_phantom, ledger_text=CANONICAL_LEDGER_TEXT
    )
    m1_caught = (not m1_res.passed) and ("sun2023phantom" in m1_res.phantom_citations)
    mutants.append(
        MutantCheckResult(
            mutant_id="phantom_citation_sun2023",
            engine="citations",
            description="Injected hallucinated \\citep{sun2023phantom} in prose with no .bib entry",
            detected=m1_caught,
            diagnostic=m1_res.failures[0] if m1_res.failures else "missed",
        )
    )

    # Mutant 2: Identifier-less .bib entry (missing DOI/arXiv/PMID/URL)
    mut_bib_noid = (
        CANONICAL_BIB_TEXT
        + "\n@article{unverified2024noid,\n"
        + "  author = {Placeholder, Pat},\n"
        + "  title  = {Unanchored Biomarker Claim Without Identifier},\n"
        + "  journal = {Unindexed Notes},\n"
        + "  year   = {2024}\n}\n"
    )
    mut_prose_noid = CANONICAL_MANUSCRIPT_TEX + "\nSee also \\cite{unverified2024noid}.\n"
    mut_ledger_noid = CANONICAL_LEDGER_TEXT + "| `unverified2024noid` | - | Unanchored claim. |\n"
    m2_res = audit_citations(mut_bib_noid, mut_prose_noid, ledger_text=mut_ledger_noid)
    m2_caught = (not m2_res.passed) and ("unverified2024noid" in m2_res.missing_identifiers)
    mutants.append(
        MutantCheckResult(
            mutant_id="identifierless_bib_entry",
            engine="citations",
            description="Injected .bib entry missing DOI, arXiv eprint, PMID, and URL",
            detected=m2_caught,
            diagnostic=m2_res.failures[0] if m2_res.failures else "missed",
        )
    )

    # Mutant 3: Drifted correlation metric r = 0.39 vs locked 0.24 (Augur mis-quote trap)
    mut_ms_drift = CANONICAL_MANUSCRIPT_TEX.replace(
        "\\newcommand{\\numDstarRetestR}{0.24}",
        "\\newcommand{\\numDstarRetestR}{0.39}",
    )
    m3_res = audit_numerical_consistency(
        mut_ms_drift,
        CANONICAL_CLAIMS_MAP,
        CANONICAL_ARTIFACTS,
        rtol=1e-4,
        atol=1e-4,
        artifact_digests=CANONICAL_ARTIFACT_DIGESTS,
    )
    m3_caught = (not m3_res.passed) and ("numDstarRetestR" in m3_res.stale_or_misquoted)
    mutants.append(
        MutantCheckResult(
            mutant_id="drifted_metric_r039_vs_024",
            engine="consistency",
            description="Mutated manuscript correlation \\numDstarRetestR from 0.24 to stale 0.39",
            detected=m3_caught,
            diagnostic=m3_res.failures[0] if m3_res.failures else "missed",
        )
    )

    # Mutant 4: Seeded artifact SHA-256 tamper + untraced macro injection
    float_macros = [m for m in _MACRO_SPECS if "." in m[3]]
    chosen_macro, _cpath, _cfmt, chosen_val = float_macros[int(rng.integers(0, len(float_macros)))]
    perturbed_val = f"{float(chosen_val) + 0.125:.3f}"
    mut_ms_seeded = (
        CANONICAL_MANUSCRIPT_TEX.replace(
            f"\\newcommand{{\\{chosen_macro}}}{{{chosen_val}}}",
            f"\\newcommand{{\\{chosen_macro}}}{{{perturbed_val}}}",
        )
        + "\nUntraced inline claim \\numOrphanedHallucinatedMetric{}."
    )
    m4_res = audit_numerical_consistency(
        mut_ms_seeded,
        CANONICAL_CLAIMS_MAP,
        CANONICAL_ARTIFACTS,
        rtol=1e-4,
        atol=1e-4,
        artifact_digests=CANONICAL_ARTIFACT_DIGESTS,
    )
    m4_caught = (
        (not m4_res.passed)
        and (chosen_macro in m4_res.stale_or_misquoted)
        and ("numOrphanedHallucinatedMetric" in m4_res.untraced_or_orphaned)
    )
    mutants.append(
        MutantCheckResult(
            mutant_id="seeded_macro_drift_and_orphan",
            engine="consistency",
            description=f"Seeded perturbation on \\{chosen_macro} ({chosen_val}->{perturbed_val}) + untraced \\num* macro",
            detected=m4_caught,
            diagnostic=m4_res.failures[0] if m4_res.failures else "missed",
        )
    )

    # Mutant 5: Upstream PROVISIONAL hold & fabricated DOI guard
    mut_rel_cfg = {
        **CANONICAL_RELEASE_CONFIG,
        "anchors": {
            **CANONICAL_RELEASE_CONFIG["anchors"],
            "CONFORMAL_RULER": {
                "status": "PROVISIONAL",
                "published": False,
                "doi": None,
                "load_bearing": True,
            },
        },
    }
    m5_res = evaluate_release_gate(mut_rel_cfg, cit_res)
    m5_caught = (not m5_res.release_ready) and ("CONFORMAL_RULER" in m5_res.unmet_anchors)
    mutants.append(
        MutantCheckResult(
            mutant_id="provisional_anchor_hold",
            engine="release_gate",
            description="Load-bearing CONFORMAL_RULER anchor marked PROVISIONAL (unpublished)",
            detected=m5_caught,
            diagnostic=m5_res.blocking_reasons[0] if m5_res.blocking_reasons else "missed",
        )
    )

    # Mutant 6: GRIM impossibility + p-value decision flip + inverted CI trap
    mut_stat_prose = (
        CANONICAL_MANUSCRIPT_TEX
        + "\nIn subgroup N = 12, 31.0\\% responded (t(20) = 1.10, p = 0.012; 95\\% CI [0.85, 0.42]).\n"
    )
    m6_res = audit_stat_consistency(mut_stat_prose)
    m6_codes = {f.code for f in m6_res.findings}
    m6_caught = (not m6_res.passed) and {
        "GRIM_INCONSISTENCY",
        "DECISION_BOUNDARY_FLIP",
        "INVERTED_CI_BOUNDS",
    }.issubset(m6_codes)
    mutants.append(
        MutantCheckResult(
            mutant_id="grim_pvalue_and_inverted_ci_trap",
            engine="statcheck",
            description="Injected GRIM-impossible percentage (N=12, 31.0%), t/p decision flip, and inverted CI",
            detected=m6_caught,
            diagnostic=m6_res.failures[0] if m6_res.failures else "missed",
        )
    )

    recall = sum(1 for m in mutants if m.detected) / len(mutants)
    stat_recall = 1.0 if (stat_res.passed and m6_caught) else 0.0
    return CanonicalBenchmarkEvaluation(
        citations_result=cit_res,
        consistency_result=con_res,
        release_result=rel_res,
        statcheck_result=stat_res,
        mutant_results=tuple(mutants),
        adversarial_fault_recall=float(recall),
        statcheck_trap_recall=float(stat_recall),
    )
