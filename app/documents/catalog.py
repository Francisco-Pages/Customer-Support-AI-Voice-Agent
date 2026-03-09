"""
Product document catalog — maps (brand, model) to pre-formatted HTML snippets
and brand to catalog HTML snippet.

All snippets are sourced from the email_template lookup table. They are ready
to embed directly into the <ul> block in the email body.
"""

# ---------------------------------------------------------------------------
# Product documents: (brand_lower, model_lower) → HTML <li> snippet(s)
# ---------------------------------------------------------------------------

PRODUCT_DOCS: dict[tuple[str, str], str] = {
    ("cooper and hunter", "a-coil and m-coil"): (
        '<li><a href="https://drive.google.com/file/d/1sVU5jP8SuvFTdxiEVLnDBHkLHabE-gBZ/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">A-Coil and M-Coil Owner\'s and Installation Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/142VZ1O2Lkq_caLIrHMdRrXiItwY-Zpj3/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">A-Coil and M-Coil Leaflet</a></li>'
    ),
    ("cooper and hunter", "air handler unit"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1NHqeD4mM4eDdTF3XzSGwavl7mwBSBWtC/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1_8y5JMLjsWH0a0urEOvs7KZKBxVdX65h/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1zVFevT7jVDmHpF_4L9eP9j-HFHSPUnk6/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1Azulsv_M3Atro7lFROmSMkxvEDC_X_cW/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "astoria"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1N7UnQD54DaXKRdZhDnMKnSAELZrze-Lt/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1qhc0mKG6vMJ2l0sHBq8k9esRt_V8xLXY/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1jIO6h_beiwqu7VvPj6H3sFbM7a9jJl9I/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1fYxrE1ZmU83K6iMUIn-VoCJbBokL_QX5/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "astoria pro"): (
        '<li><a href="https://drive.google.com/file/d/1N7UnQD54DaXKRdZhDnMKnSAELZrze-Lt/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Astoria Pro Owner\'s Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1Bvdp_LIe1XLT7nR1NGdGDjbPdVPObQPv/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Astoria Pro Leaflet</a></li>'
    ),
    ("cooper and hunter", "ceiling cassette"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/12G8KYEt4J5GWzEVS6udtjMOu_sW7gVNX/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/16prnUOT1SqmQDjqvCz4XHDo9jcFEpA5K/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1RbpaiTwvMeWwQcft9t9hGFsahgIvvToZ/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/19nHOb6y4FBMpUgQ1b6zKtddA4oarHm7Y/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "high-static slim duct"): (
        '<li><a href="https://drive.google.com/file/d/1iJPFHjLdibMYIsJ857pFuT42wS5ytZkl/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">High Static Slim Duct</a></li>'
        '<li><a href="https://drive.google.com/file/d/1SLQ2M4iqnz-Z3DXkt6TwVNZwMJsG_xPr/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">High-Static Slim Duct Leaflet</a></li>'
    ),
    ("cooper and hunter", "medium-static slim duct"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1UXqgTd1FV7geydeFNcznpASjUB6cPM_i/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/17yK8xxLrFBM9j7UqdM7OdMZ46hvM9SST/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1SLQ2M4iqnz-Z3DXkt6TwVNZwMJsG_xPr/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1pDyhojvy_U-2-WKo4SnGwOzC5PByaUxV/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "multi-zone"): (
        '<li>Installation Manuals: <a href="https://drive.google.com/file/d/12LjqQ8jIukGsoojZU-8uKHapYasmE542/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1v8zC60ZEXapv2i1r5jjcma93UkVUXWW3/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1cgoQFLwZ0nWmW5Quy-SSAIpDbgzho2Vy/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1hWMcz5STiGTcwsPTamRVlEBDm8A5Nr9B/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Combination Charts for Hyper Systems: <a href="https://drive.google.com/file/d/15hQlRcmtb2TQdtkoBR3mPs90qm14NBVF/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1P4lO16gRJqWAUh8jhpMojRiejerQou7x/view?usp=drivesdk" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Combination Charts for Regular Systems: <a href="https://drive.google.com/file/d/16qTZ1PslN4oq824ZKMj5QRTvaqz_QHfn/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1n_aBj_gct6JK_I9EOxAuNwA87SeT1JnA/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "ny mia"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1T2RFNyaGJTKLklsAN1vk49ujiIjlJ3XW/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1ocgVDLvQhpjYu34wb9wqg18tlpPjKkg-/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/14gzX7XkpVl71jAi68fESfLeiseLSlPQb/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1Jr-UeeN1P_tcRAjDxds021ZZT5rUDznt/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "mini floor console"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1E-uhaKZZgiVQ_gN0Jv8iOEv7Quu6KUUq/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1_8y5JMLjsWH0a0urEOvs7KZKBxVdX65h/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1Apml7NnFRNH6QMCGBEleV3bGd7bj6nv3/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/19LVEPM9fewRZEwsmhWGtKl_ZZkaGLeQ1/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "olivia"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1pkelbeVMrfn2i1nxGEuqQwjTmtaWutkL/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/166vavs0fMwkBxQYr6X5RfSxrKltAK3vH/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1kMSgLDbsayP0-d_KO3hmk975U8SX8MOA/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1XF4verTiIfDLiqMiJSlYrbxxUJyFumcH/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "olivia midnight"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1pkelbeVMrfn2i1nxGEuqQwjTmtaWutkL/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1oHh9OMJjimaA7kdre9OKoU_h3Cbe6p3X/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1qIQKuuLvTD31YjOA2BanWQ74Oyvk9c5b/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1LpsdEUQU1Wnp3eBK9qDKdrnJQPBOhtDn/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "one-way cassette"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1yMMpSYvok6cc48XhtVbLZg9-wXKWIjNk/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/13Xi8vbowhAWrxqQ3_GTB_1nXqCQmLBRE/view?usp=sharing" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1REpjjY_FwjKi2Eri6pZ2-8BUWSwoI3v9/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/13Xi8vbowhAWrxqQ3_GTB_1nXqCQmLBRE/view?usp=sharing" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "peaq"): (
        '<li><a href="https://drive.google.com/file/d/1misPqHb93iq5usCi7xVbpLyy_Lan7e4t/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PEAQ</a></li>'
        '<li><a href="https://drive.google.com/file/d/16F7IadG9phWj3WS60ThYlfrh2frm0wAY/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PEAQ Leaflet</a></li>'
    ),
    ("cooper and hunter", "ptac"): (
        '<li><a href="https://drive.google.com/file/d/1HVsvj6ZGvffq03yx9eN8SXK6z5YtvcJY/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PTAC</a></li>'
        '<li><a href="https://drive.google.com/file/d/1fX5sPA0Cgo1GgiwYUZdWyx6sjkljHnXz/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PTAC Leaflet</a></li>'
    ),
    ("cooper and hunter", "sophia"): (
        '<li>Leaflets: <a href="https://drive.google.com/file/d/13XDE4FGcx4_hG5YzF3jbgrzWwTVizkaS/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Wall Mount Leaflet</a>, <a href="https://drive.google.com/file/d/14leboqAIKYKw-PsNCZZPxg8uGPMVlWUN/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Multi-Zone Leaflet</a></li>'
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/19nroFCv-GkUbALwJTv6EdcFgW4L1Z-a-/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Ceiling Cassette Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1WX5uPcs6Loa5PX27Y6_zMmnUy5g0F6wK/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Floor Ceiling Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1gkYOWhCRU4BGN_UUIlU_LC7jo1YJq1MD/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Hyper Multi-Zone Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1mTlq0C3ADTvt6QAK7PGQmuapMfLlEKqp/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Regular Multi-Zone Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1czAqmQetqwsjfm-b4KLlk6t0oeRTgz4A/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Wall Mount Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1-zJmbGMwxGfQgXZUWjGxs8aT9DsIhtIM/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sophia Wall Mount Remote Control Owner\'s Manual</a></li>'
    ),
    ("cooper and hunter", "universal floor ceiling"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1GHnTwBXyBljx0ttRioVbJJVOeeDyNnF2/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/11sAJ_0ip7bf51kx1odz1WdzmsVNHC7nq/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1xbBA-3QXCoDM8izlCvRdilnh96pIGwl3/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
    ),
    ("cooper and hunter", "controllers"): (
        '<li><a href="https://drive.google.com/file/d/1l7HIuoSOoQoq7thLvhXCmgeW9F9R8Mab/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">24V Wired controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1XDJ1CPtbYbNKTLoyrUaief_4OJhLeFYL/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">120F Wired controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1PjdzypxVATwfL2HdX1v_lyy_OqyA1c2o/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">120N Wired controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1Fle2euA2rlpIfOZk5MGFlZWGSAslDfI0/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Universal remote controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1amvXt13DGI7Ms5pS5inJezJ3oZmGrkv3/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Remote controller (with humidity control) manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1bq_t-cxucX87i5OzA5pZl5g4k4z-LChg/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Smart Kit controller manual</a></li>'
    ),
    # Olmo
    ("olmo", "air handler unit"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1FyUoXl55VfD8a4o6bQw-JU5I9YmkLKBA/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Indoor Unit Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1fukRMDgI31ogzgOOnchPc9SSqmY1qpWy/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Outdoor Unit Owner\'s Manual</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1MKnmxryZZt6yx7m_eL5oI2I7s_3KLju-/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Air Handler Unit Leaflet</a></li>'
    ),
    ("olmo", "alpic eco"): (
        '<li><a href="https://drive.google.com/file/d/1QtSvO9mhC4V_WZ6eH6rj7jwCFVmVIlT4/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Alpic Eco Owner\'s Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1x5KSMw8GYp-F1zydmwDt7YVyv_4R97si/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Alpic Eco Leaflet</a></li>'
    ),
    ("olmo", "ptac"): (
        '<li><a href="https://drive.google.com/file/d/1ww-p8P10kATqACNY5bQxg8uzV3fqiDBs/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PTAC Owner\'s Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1y5Bciq6ck2uDMEJYgskTGqjZckyQ4Umn/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PTAC Remote Control Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1NW8LSJ9D0ZAP6swWYc8H_nJ_Sqn3x5Tq/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PTAC Leaflet</a></li>'
    ),
    ("olmo", "scandic"): (
        '<li><a href="https://drive.google.com/file/d/1w303JzlhfQFoI-cqMJP2dAOds0o-vMWI/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Scandic Owner\'s Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1bxK92i1UNM9ZM9v8SmKh2G6djsx0NLBx/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Scandic Leaflet</a></li>'
    ),
    ("olmo", "single-zone"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1BCDCx5wUE3Nq5wqY5cT-P2XBS7bXJM01/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a>, <a href="https://drive.google.com/file/d/1iUCMAFi_7B0T1YMfbnaUUmc_GOol5xsG/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R32 Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1GD_lFSkrP6iorjhNOxLdfYB7YiALV1PZ/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a>, <a href="https://drive.google.com/file/d/1en36w2cf0h6ZtasY9UcRkCvFM4t_DQuL/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R32 Model</a></li>'
        '<li>Accessories: <a href="https://drive.google.com/file/d/1w0Kgpgmxkm2RUD4Yl6m6a4FIMN_15mZe/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Remote Control Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1ntoJgqMoau1eJlF03-KJmnxZAnJKHnJm/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wifi Owner\'s Manual</a></li>'
    ),
    ("olmo", "multi-zone"): (
        '<li>Indoor Unit Owner\'s Manuals: <a href="https://drive.google.com/file/d/1DZ59Yjkks3zhsNoG9bD74jmjudnwdIQo/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1Eb9iy0zmzNLCiv9pEb5PIFvZaLlInwVW/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Outdoor Unit Owner\'s Manuals: <a href="https://drive.google.com/file/d/13wNE2aU7Dk2Y2DECt08R7d09qowIFigF/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1u2uhVU53es4xLJ1rkaWCT2Yxguc2eQdK/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1gBqW2OVpQbmz4vhg1CY_hGt9OIJu7MIh/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R454B Model</a>, <a href="https://drive.google.com/file/d/1Ql3BYWiRYYK6vdDAcLbIinXJ0Kt5RDK9/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a></li>'
        '<li>Accessories: <a href="https://drive.google.com/file/d/1-GdW9wbmrRq94Zt2PsYhvUxap78oCNfJ/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wifi Owner\'s Manual</a></li>'
    ),
    ("olmo", "tropic"): (
        '<li><a href="https://drive.google.com/file/d/1aGtUwB5HdA05Ej05nrJ94g1UlEv14VDF/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Tropic Owner\'s Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1SDdjfhxikAM8b3VZwnyDrHMR5_I_89Fd/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Tropic Leaflet</a></li>'
    ),
    ("olmo", "ttw"): (
        '<li><a href="https://drive.google.com/file/d/1PTGmQW5mAiieRh-8VvKM_t6rTAGI5T1-/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">TTW Owner\'s Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/19G32gJ0Ii0cIPDDbW8XC6s2gbilSDa7H/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">TTW Remote Control Manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1q7P2qFnNhXpoUFL_OHb3ayfqcEAbo2c8/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">TTW Leaflet</a></li>'
    ),
    ("olmo", "wac"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/126sWyg8LCD2T6vSBaDeaZtVFqPKc4r2L/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">WAC (8K)</a>, <a href="https://drive.google.com/file/d/1WitbzLbA8deUi9wSpi4MnaJ6PYYkyH1c/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">WAC (18K)</a></li>'
        '<li><a href="https://drive.google.com/file/d/1DDVwhKOBDyNR4aYVzfFImhy5ggIkSsSS/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">WAC Leaflet</a></li>'
    ),
    ("olmo", "controllers"): (
        '<li><a href="https://drive.google.com/file/d/1w0Kgpgmxkm2RUD4Yl6m6a4FIMN_15mZe/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sierra multi-zone remote controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1-GdW9wbmrRq94Zt2PsYhvUxap78oCNfJ/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sierra multi-zone wi-fi controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1ntoJgqMoau1eJlF03-KJmnxZAnJKHnJm/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Sierra single-zone wi-fi controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1y5Bciq6ck2uDMEJYgskTGqjZckyQ4Umn/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">PTAC remote controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/19G32gJ0Ii0cIPDDbW8XC6s2gbilSDa7H/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">TTW remote controller manual</a></li>'
    ),
    # Bravo
    ("bravo", "single-zone"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1LZkRhSxJzVBIaXRif7Q7v5XevoEOURdm/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a>, <a href="https://drive.google.com/file/d/1Sl7FWd7HSqtAsOcIi4YnJ_L3XDYy-EaN/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R32 Model</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/1LO2mEdq43TcPMCKqg1RpTHBnfr5fpfiY/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R410A Model</a>, <a href="https://drive.google.com/file/d/1xzVYsDM8RgZYKGJXOQQhZeBphqFmdHbN/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">R32 Model</a></li>'
        '<li>Accessories: <a href="https://drive.google.com/file/d/1xS2VnNgu3fgtgx1XzTDU_EXi_2HMkmjj/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wifi Owner\'s Manual</a></li>'
    ),
    ("bravo", "multi-zone"): (
        '<li>Owner\'s Manuals: <a href="https://drive.google.com/file/d/1S5kENT6x0XRLFwar84omuWMBqi8cQSyL/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wall-Mount</a>, <a href="https://drive.google.com/file/d/1gbX8LmCnuCNUjBEDe6vhtOCs5M-ISfs9/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Ceiling Cassette</a>, <a href="https://drive.google.com/file/d/1uP-b1HP5LARibXkz7Sgx3u382iNjy_7_/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Floor Ceiling</a>, <a href="https://drive.google.com/file/d/16IhquPxMgUBgKgvm-wTGlG4RckupEDB5/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Slim Duct</a>, <a href="https://drive.google.com/file/d/1uDRqsun96T7OGuoh3h7Lect-4NrN2jJi/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Outdoor Unit</a></li>'
        '<li>Leaflets: <a href="https://drive.google.com/file/d/12mqXvSh-XjRqVdqWtaCcz3DBwGYcj0cG/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Bravo Multi-Zone Units</a></li>'
        '<li>Accessories: <a href="https://drive.google.com/file/d/1gXtLwjMgpXFFZSe7-mo0fIXbpa0XOXBC/view?usp=sharing" target="_blank" style="color:#2563eb; text-decoration:underline;">Remote Control Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1qtj-bHs1kY_rvZdgpHGh21AcHnZpYa3N/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Smart App Owner\'s Manual</a>, <a href="https://drive.google.com/file/d/1Z26qxu3dQ9Azgh8UTL9mi738SZyDllv-/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wired Controller</a></li>'
    ),
    ("bravo", "controllers"): (
        '<li><a href="https://drive.google.com/file/d/1gXtLwjMgpXFFZSe7-mo0fIXbpa0XOXBC/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Remote controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1Z26qxu3dQ9Azgh8UTL9mi738SZyDllv-/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wired controller manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1qtj-bHs1kY_rvZdgpHGh21AcHnZpYa3N/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Smart App manual</a></li>'
        '<li><a href="https://drive.google.com/file/d/1xS2VnNgu3fgtgx1XzTDU_EXi_2HMkmjj/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Wi-fi controller manual</a></li>'
    ),
}

# ---------------------------------------------------------------------------
# Brand catalogs: brand_lower → HTML snippet
# ---------------------------------------------------------------------------

BRAND_CATALOGS: dict[str, str] = {
    "cooper and hunter": (
        '<h3 style="margin:0 0 10px 0; font-size:14px; line-height:1.4; font-weight:normal; color:#4b5563;">'
        "If you want more information about other Cooper and Hunter products, check out our catalogs below: "
        '</h3><ul style="margin:0 0 16px 20px; padding:0; font-size:14px; line-height:1.6; color:#4b5563;">'
        '<li><a href="https://drive.google.com/file/d/1iBP3icqXupzaoJT--RAWVK66pVRTKpf3/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Cooper and Hunter 2025 Product Catalog</a></li>'
        '<li><a href="https://drive.google.com/file/d/1NXzOmc77Y8P-J9OadoZ2Gdv8zpKCoS9C/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Cooper and Hunter 2024 Product Catalog</a></li>'
        "</ul>"
    ),
    "olmo": (
        '<h3 style="margin:0 0 10px 0; font-size:14px; line-height:1.4; font-weight:normal; color:#4b5563;">'
        "If you want more information about other Olmo products, check out our catalogs below: "
        '</h3><ul style="margin:0 0 16px 20px; padding:0; font-size:14px; line-height:1.6; color:#4b5563;">'
        '<li><a href="https://drive.google.com/file/d/1gBqW2OVpQbmz4vhg1CY_hGt9OIJu7MIh/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Olmo R32 and R454B Product Catalog</a></li>'
        '<li><a href="https://drive.google.com/file/d/1cDAB6Dn71rWowCAZmVhfClv8uPYxAoOD/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Olmo R410A Product Catalog</a></li>'
        "</ul>"
    ),
    "bravo": (
        '<h3 style="margin:0 0 10px 0; font-size:14px; line-height:1.4; font-weight:normal; color:#4b5563;">'
        "If you want more information about other Bravo products, check out the catalog below: "
        '</h3><ul style="margin:0 0 16px 20px; padding:0; font-size:14px; line-height:1.6; color:#4b5563;">'
        '<li><a href="https://drive.google.com/file/d/1cGL-gFcWtdhGQgYJCg6hcID25pnMdAyY/view?usp=share_link" target="_blank" style="color:#2563eb; text-decoration:underline;">Bravo R32 Product Catalog</a></li>'
        "</ul>"
    ),
}


def get_product_html(brand: str, model: str) -> str | None:
    """Return the document HTML snippet for a brand+model, or None if not found."""
    return PRODUCT_DOCS.get((brand.lower().strip(), model.lower().strip()))


def get_catalog_html(brand: str) -> str | None:
    """Return the catalog HTML snippet for a brand, or None if not found."""
    return BRAND_CATALOGS.get(brand.lower().strip())


def get_documents_sms_text(brand: str, model: str) -> str | None:
    """
    Return a plain-text list of document links for a brand+model, suitable
    for SMS. Extracts href + link text from the HTML snippets.
    Returns None if the brand+model is not found.
    """
    import re as _re

    product_html = get_product_html(brand, model)
    if product_html is None:
        return None

    catalog_html = get_catalog_html(brand)

    def _links(html: str) -> list[tuple[str, str]]:
        # returns [(url, text), ...] — note findall order matches group order
        return _re.findall(r'href="([^"]+)"[^>]*>([^<]+)<', html)

    lines = [f"{model.title()} — Documents:"]
    for url, text in _links(product_html):
        if url:
            lines.append(f"• {text}: {url}")

    if catalog_html:
        lines.append(f"\n{brand.title()} — Catalogs:")
        for url, text in _links(catalog_html):
            if url:
                lines.append(f"• {text}: {url}")

    return "\n".join(lines)
