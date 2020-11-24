import math

import numba as nb
import numpy as np
from numba import cuda
from numba.cuda.random import xoroshiro128p_uniform_float32

from .monitors import fmri, fmri_gpu


def dr(r, V, o_tau, pi, tau, Delta):
    "Time-derivative of r(t) in the Montbrio model."
    return o_tau * (Delta / (pi * tau) + 2 * V * r)


def dV(r, V, o_tau, pi, tau, eta, J, I, cr, rc, cv, Vc):
    "Time-derivative of V(t) in the Montbrio model."
    return o_tau * (V ** 2 - (pi ** 2) * (tau ** 2) * (r ** 2) + eta + J * tau * r + I + cr * rc + cv * Vc)


def make_rk4_rV(dt, sqrt_dt, o_6, use_cuda=False):
    if use_cuda:
        jit = cuda.jit(inline='always',device=True)
    else:
        jit = nb.njit(fastmath=True,boundscheck=False,inline='always')
    dr_ = jit(dr)
    dV_ = jit(dV)
    def rk4_rV(it, nrV, rti, Vti,
               o_tau, pi, tau, Delta, eta, J, I, cr, rc, cv, Vc,
               r_sigma, V_sigma, z0, z1):
        itx = cuda.threadIdx.x
        dr_0 = dr_(rti, Vti, o_tau, pi, tau, Delta)
        dV_0 = dV_(rti, Vti, o_tau, pi, tau, eta, J, I, cr, rc, cv, Vc)
        kh = nb.float32(0.5)
        dr_1 = dr_(rti + dt * kh * dr_0, Vti + dt * kh * dV_0, o_tau, pi, tau, Delta)
        dV_1 = dV_(rti + dt * kh * dr_0, Vti + dt * kh * dV_0, o_tau, pi, tau, eta, J, I, cr, rc, cv, Vc)
        dr_2 = dr_(rti + dt * kh * dr_1, Vti + dt * kh * dV_1, o_tau, pi, tau, Delta)
        dV_2 = dV_(rti + dt * kh * dr_1, Vti + dt * kh * dV_1, o_tau, pi, tau, eta, J, I, cr, rc, cv, Vc)
        kh = nb.float32(1.0)
        dr_3 = dr_(rti + dt * kh * dr_2, Vti + dt * kh * dV_2, o_tau, pi, tau, Delta)
        dV_3 = dV_(rti + dt * kh * dr_2, Vti + dt * kh * dV_2, o_tau, pi, tau, eta, J, I, cr, rc, cv, Vc)
        nrV[0, itx] = rti + o_6 * dt * (dr_0 + 2 * (dr_1 + dr_2) + dr_3) + sqrt_dt * r_sigma * z0
        nrV[0, itx] *= nrV[0, itx] > 0
        nrV[1, itx] = Vti + o_6 * dt * (dV_0 + 2 * (dV_1 + dV_2) + dV_3) + sqrt_dt * V_sigma * z1
    return jit(rk4_rV)

# def make_box_muller():
#     import numba.cuda.random as cr
#     @cuda.jit(inline='always')
#     def box_muller(rngs, offset, out):
#         it = cuda.threadIdx.x
#     return box_muller

def setup_const(nh, nto, nn, dt):
    nh, nn = [nb.uint32(_) for _ in (nh, nn)]
    dt, pi = [nb.float32(_) for _ in (dt, np.pi)]
    sqrt_dt = nb.float32(np.sqrt(dt))
    o_nh = nb.float32(1 / nh * nto)
    o_6 = nb.float32(1 / 6)
    return nh, nn, dt, pi, sqrt_dt, o_nh, o_6


def make_gpu_loop(nh, nto, nn, dt, cfpre, cfpost, blockDim_x):
    nh, nn, dt, pi, sqrt_dt, o_nh, o_6 = setup_const(nh, nto, nn, dt)
    rk4_rV = make_rk4_rV(dt, sqrt_dt, o_6, use_cuda=True)
    @cuda.jit(fastmath=True)
    def loop(_, r, V, rngs, w, d, tavg, bold_state, bold_out, I, Delta, eta, tau, J, cr, cv, r_sigma, V_sigma):
        it = cuda.blockIdx.x * cuda.blockDim.x + cuda.threadIdx.x
        nt = cuda.blockDim.x * cuda.gridDim.x
        itx = cuda.threadIdx.x
        # if it==0: print('hello from ', cuda.blockIdx.x, cuda.threadIdx.x)
        # if it==0: print("NT =", NT)
        o_tau = nb.float32(1 / tau)
        # if it==0: print("o_tau = ", o_tau)
        assert r.shape[0] == V.shape[0] == nh  # shape asserts help numba optimizer
        assert r.shape[1] == V.shape[1] == nn
        # if it==0: print("creating nrV shared..")
        nrV = cuda.shared.array((2, blockDim_x), nb.float32)
        # if it==0: print("zeroing tavg..")
        for j in range(nto):
            for i in range(nn):
                tavg[j, 0, i, it] = nb.float32(0.0)
                tavg[j, 1, i, it] = nb.float32(0.0)
        # if it==0: print('tavg zero\'d', -1, nh - 1)
        for t0 in range(-1, nh - 1):
            # if it==0: print('t0=', t0)
            t = nh-1 if t0<0 else t0
            # if it==0: print('t=', t)
            t1 = t0 + 1
            # if it==0: print('t1=', t1)
            # if it==0: print('nh//nto', nh // nto)
            # if it==0: print('t1=', t1)
            t0_nto = t0 // (nh // nto)
            # if it==0: print(t, t1, t0_nto)
            for i in range(nn):
                rc = nb.float32(0) # using array here costs 50%+
                Vc = nb.float32(0)
                for j in range(nn):
                    dij = (t - d[i, j] + nh) & (nh-1)
                    rc += w[i, j] * cfpre(r[dij, j, it], r[t, i, it])
                    Vc += w[i, j] * cfpre(V[dij, j, it], V[t, i, it])
                rc = cfpost(rc)
                Vc = cfpost(Vc)
                # RNG + Box Muller
                pi_2 = nb.float32(np.pi * 2)
                u1 = xoroshiro128p_uniform_float32(rngs, t1*nt*nn*2 + i*nt*2 + it)
                u2 = xoroshiro128p_uniform_float32(rngs, t1*nt*nn*2 + i*nt*2 + it + nt)
                z0 = math.sqrt(-nb.float32(2.0) * math.log(u1)) * math.cos(pi_2 * u2)
                z1 = math.sqrt(-nb.float32(2.0) * math.log(u1)) * math.sin(pi_2 * u2)
                # RK4
                rk4_rV(it, nrV, r[t, i, it], V[t, i, it],
                       o_tau, pi, tau, Delta, eta, J, I, cr, rc, cv, Vc,
                       r_sigma, V_sigma, z0, z1)
                r[t1, i, it] = nrV[0, itx]
                V[t1, i, it] = nrV[1, itx]
                # if it==0: print(nrV[0, it], nrV[1, it], o_nh)
                tavg[t0_nto, 0, i, it] += nrV[0, itx] * o_nh
                tavg[t0_nto, 1, i, it] += nrV[1, itx] * o_nh
                # if it==0: print(t1, o_nh, tavg[t0_nto, 0, i, it], tavg[t0_nto, 1, i, it])
                bold_out[i, it] = fmri_gpu(it, bold_state[i], nrV[0, itx], dt)
                # if it==0: print("loop body done")
    return loop


# nto is num samples to average over
def make_gpu_loop_no_delay(nh, nto, nn, dt, cfpre, cfpost, blockDim_x):
    nh, nn, dt, pi, sqrt_dt, o_nh, o_6 = setup_const(nh, nto, nn, dt)
    rk4_rV = make_rk4_rV(dt, sqrt_dt, o_6, use_cuda=True)
    @cuda.jit(fastmath=True)
    def loop(_, r, V, rngs, w, d, tavg, bold_state, bold_out, I, Delta, eta, tau, J, cr, cv, r_sigma, V_sigma):
        it = cuda.blockIdx.x * cuda.blockDim.x + cuda.threadIdx.x
        nt = cuda.blockDim.x * cuda.gridDim.x
        itx = cuda.threadIdx.x
        # if it==0: print('hello from ', cuda.blockIdx.x, cuda.threadIdx.x)
        # if it==0: print("NT =", NT)
        o_tau = nb.float32(1 / tau)
        # if it==0: print("o_tau = ", o_tau)
        assert r.shape[0] == V.shape[0] == nh  # shape asserts help numba optimizer
        assert r.shape[1] == V.shape[1] == nn
        # if it==0: print("creating nrV shared..")
        nrV = cuda.shared.array((2, blockDim_x), nb.float32)
        # if it==0: print("zeroing tavg..")
        for i in range(nn):
            tavg[0, i, it] = nb.float32(0.0)
            tavg[1, i, it] = nb.float32(0.0)
        # if it==0: print('tavg zero\'d', -1, nh - 1)
        for t0 in range(nto):
            for i in range(nn):
                rc = nb.float32(0) # using array here costs 50%+
                Vc = nb.float32(0)
                for j in range(nn):
                    rc += w[i, j] * cfpre(r[0, j, it], r[0, i, it])
                    Vc += w[i, j] * cfpre(V[0, j, it], V[0, i, it])
                rc = cfpost(rc)
                Vc = cfpost(Vc)
                # RNG + Box Muller
                pi_2 = nb.float32(np.pi * 2)
                u1 = xoroshiro128p_uniform_float32(rngs, i*nt*2 + it)
                u2 = xoroshiro128p_uniform_float32(rngs, i*nt*2 + it + nt)
                z0 = math.sqrt(-nb.float32(2.0) * math.log(u1)) * math.cos(pi_2 * u2)
                z1 = math.sqrt(-nb.float32(2.0) * math.log(u1)) * math.sin(pi_2 * u2)
                # RK4
                rk4_rV(it, nrV, r[0, i, it], V[0, i, it],
                       o_tau, pi, tau, Delta, eta, J, I, cr, rc, cv, Vc,
                       r_sigma, V_sigma, z0, z1)
                r[1, i, it] = nrV[0, itx]
                V[1, i, it] = nrV[1, itx]
                # if it==0: print(nrV[0, it], nrV[1, it], o_nh)
                tavg[0, i, it] += nrV[0, itx] * o_nh
                tavg[1, i, it] += nrV[1, itx] * o_nh
                # if it==0: print(t1, o_nh, tavg[t0_nto, 0, i, it], tavg[t0_nto, 1, i, it])
                bold_out[i, it] = fmri_gpu(it, bold_state[i], nrV[0, itx], dt)
                # if it==0: print("loop body done")
            for i in range(nn):
                r[0, i, it] = r[1, i, it]
                V[0, i, it] = V[1, i, it]
    return loop


# launch (n_subject, n_noise, n_coupling) (n_node,)
def make_gpu_loop_no_delay2(nh, nto, nn, dt, cfpre, cfpost, blockDim_x):
    nh, nn, dt, pi, sqrt_dt, o_nh, o_6 = setup_const(nh, nto, nn, dt)
    pi_2 = nb.float32(np.pi * 2)
    rk4_rV = make_rk4_rV(dt, sqrt_dt, o_6, use_cuda=True)
    @cuda.jit(fastmath=True)
    def loop(_, r, V, rngs, w, d, tavg, bold_state, bold_out, I, Delta, eta, tau, J, cr, cv, r_sigma, V_sigma):
        assert r.shape[0] == V.shape[0] == nh  # shape asserts help numba optimizer
        assert r.shape[1] == V.shape[1] == nn
        assert cuda.blockDim.x == nn and cuda.blockDim.y == 1
        i = cuda.threadIdx.x  # node
        # sim index and num sim
        n_subj, i_subj = cuda.gridDim.x, cuda.blockIdx.x
        n_nois, i_nois = cuda.gridDim.y, cuda.blockIdx.y
        n_coup, i_coup = cuda.gridDim.z, cuda.blockIdx.z
        it = i_subj * n_nois * n_coup + i_nois * n_coup + i_coup
        nt = n_subj * n_nois * n_coup
        o_tau = nb.float32(1 / tau)
        nrV = cuda.shared.array((2, nn), nb.float32)
        jrV = cuda.shared.array((2, nn), nb.float32)
        tavg[it, 0, i] = nb.float32(0.0)
        tavg[it, 1, i] = nb.float32(0.0)
        for t0 in range(nto):
            rc = nb.float32(0) # using array here costs 50%+
            Vc = nb.float32(0)
            # preload state for j loop
            jrV[0, i] = r[it, 0, i]
            jrV[1, i] = V[it, 0, i]
            cuda.syncthreads()
            for j in range(nn):
                rc += w[j, i] * cfpre(jrV[0, j], jrV[0, i])
                Vc += w[j, i] * cfpre(jrV[1, j], jrV[1, i])
            rc = cfpost(rc)
            Vc = cfpost(Vc)
            # RNG Box Muller (~50% time)
            u1 = xoroshiro128p_uniform_float32(rngs, it*nn + i)
            u2 = xoroshiro128p_uniform_float32(rngs, it*nn + i + nn)
            # Box-Muller
            R = math.sqrt(-nb.float32(2.0) * math.log(u1))
            z0 = R * math.cos(pi_2 * u2)
            z1 = R * math.sin(pi_2 * u2)
            # RK4
            rk4_rV(i, nrV, r[it, 0, i], V[it, 0, i],
                   o_tau, pi, tau, Delta, eta, J, I, cr, rc, cv, Vc,
                   r_sigma, V_sigma, z0, z1)
            r[it, 1, i] = nrV[0, i]
            V[it, 1, i] = nrV[1, i]
            tavg[it, 0, i] += nrV[0, i] * o_nh
            tavg[it, 1, i] += nrV[1, i] * o_nh
            bold_out[i] = fmri_gpu(it, bold_state[i], nrV[0], dt)
            cuda.syncthreads()
            r[it, 0, i] = r[it, 1, i]
            V[it, 0, i] = V[it, 1, i]
    return loop


def make_loop(nh, nto, nn, dt, cfpre, cfpost):
    nh, nn, dt, pi, sqrt_dt, o_nh, o_6 = setup_const(nh, nto, nn, dt)
    rk4_rV = make_rk4_rV(dt, sqrt_dt, o_6)
    @nb.njit(boundscheck=False, fastmath=True)
    def loop(nrV, r, V, wrV, w, d, tavg, bold_state, bold_out, I, Delta, eta, tau, J, cr, cv, r_sigma, V_sigma):
        o_tau = nb.float32(1 / tau)
        assert r.shape[0] == V.shape[0] == nh  # shape asserts help numba optimizer
        assert r.shape[1] == V.shape[1] == nn
        for j in range(nto):
            for i in range(nn):
                tavg[j, 0, i] = nb.float32(0.0)
                tavg[j, 1, i] = nb.float32(0.0)
        for t0 in range(-1, nh - 1):
            t = nh-1 if t0<0 else t0
            t1 = t0 + 1
            t0_nto = t0 // (nh // nto)
            for i in range(nn):
                rc = nb.float32(0) # using array here costs 50%+
                Vc = nb.float32(0)
                for j in range(nn):
                    dij = (t - d[i, j] + nh) & (nh-1)
                    rc += w[i, j] * cfpre(r[dij, j], r[t, i])
                    Vc += w[i, j] * cfpre(V[dij, j], V[t, i])
                rc = cfpost(rc)
                Vc = cfpost(Vc)
                rk4_rV(0, nrV, r[t, i], V[t, i],
                       o_tau, pi, tau, Delta, eta, J, I, cr, rc, cv, Vc,
                       r_sigma, V_sigma, wrV[0, t1, i], wrV[1, t1, i])
                r[t1, i] = nrV[0, 0]
                V[t1, i] = nrV[1, 0]
                tavg[t0_nto, 0, i] += r[t1, i] * o_nh
                tavg[t0_nto, 1, i] += V[t1, i] * o_nh
                bold_out[i] = fmri(bold_state[i], tavg[0, 0, i], dt)
    return loop