COMFYUI CUSTOM-NODE PROFILE (append to each round prompt)

When the target repo is a ComfyUI custom-node pack, also verify the
domain invariants below. Cite the real node file/class for every claim; if you
cannot see the code, write "verify: <what>" rather than asserting it. These are
ComfyUI-specific failure modes the general rounds do not weight.

1. NODE-CLASS CONTRACT
   - Every exported node class is registered in NODE_CLASS_MAPPINGS (and given a
     label in NODE_DISPLAY_NAME_MAPPINGS). A class that is defined but not mapped
     is dead -- it never loads. Flag any node in the plan that is not wired into
     the mappings.
   - INPUT_TYPES is a @classmethod returning a dict with "required" (and optional
     "optional"/"hidden") keys. Each input is (TYPE, {options}) where TYPE is a
     real type string ("IMAGE", "LATENT", "MODEL", "CONDITIONING", "STRING",
     "INT", "FLOAT", ...) or a list-of-choices for a dropdown.
   - RETURN_TYPES is a tuple (note the trailing comma for a single output),
     length-matched to what FUNCTION actually returns; RETURN_NAMES if present
     must be the same length. CATEGORY and FUNCTION must be set.
   - Widget order is POSITIONAL: appending an optional input is safe; inserting
     one mid-list silently shifts every saved widget value in existing graphs.

2. TENSOR LAYOUT / SHAPE CONVENTIONS
   - ComfyUI IMAGE tensors are float32 in [0,1], shape [B, H, W, C] (channels
     LAST), C usually 3. MASK is [B, H, W]. LATENT is a dict {"samples": tensor}
     with the model's own channel layout (commonly [B, C, H, W]). Flag any node
     that assumes channels-first for IMAGE or forgets the batch dim.
   - Check dtype/device handling: tensors may arrive on cuda or cpu; a node must
     not hard-assume one. Verify .to(device)/.cpu() moves are correct and that
     outputs match the declared RETURN_TYPES layout.

3. VRAM / MODEL MANAGEMENT
   - Heavy models should load through comfy.model_management (residency, offload,
     and eviction are managed there) rather than being pinned in module globals.
     Flag any plan that holds a model resident across runs without an eviction or
     free path, or that bypasses model_management's load/offload.
   - Verify large allocations are freed (or handed to model_management) so a
     long ComfyUI session does not leak VRAM across queued prompts.

4. IS_CHANGED / CACHING CORRECTNESS
   - ComfyUI caches a node's output and re-runs only when inputs change. If a
     node depends on external state (a file on disk, a clock, RNG, a network
     fetch), it must implement IS_CHANGED to return a value that varies when that
     state changes -- otherwise it serves stale cached output. Flag any node with
     hidden external inputs and no IS_CHANGED, and any IS_CHANGED that is more
     conservative/looser than the node's real dependencies.

5. IMPORT ISOLATION (no heavy imports at module top)
   - The module top level is imported at ComfyUI startup. Heavy or optional
     dependencies (torch extras, model libraries, CUDA ext) imported at top level
     slow every boot and hard-crash startup if missing. Move them inside the
     node method (lazy import) so an unrelated missing dep cannot take down the
     whole node pack. Flag top-level imports of optional/heavy packages.
   - Side effects at import time (downloading weights, opening files, mutating
     global state) are a defect -- they run for every user on every boot.
