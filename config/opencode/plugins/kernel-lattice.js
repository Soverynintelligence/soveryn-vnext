/**
 * Kernel lattice (house OpenCode plugins path). Default OFF.
 * Same gate as JIT_TOOL_RETRY. Do not enable in prod until Pi dry sessions pass.
 * KERNEL_LATTICE=1 / KERNEL_MEMORY=1 / JIT_MEMORY=1
 */
function enabled() {
  const v = process.env.KERNEL_LATTICE || process.env.KERNEL_MEMORY || process.env.JIT_MEMORY || "0"
  return v === "1" || v === "true" || v === "TRUE"
}

export const KernelLatticePlugin = async () => {
  if (!enabled()) return {}
  return {}
}

export default KernelLatticePlugin
