# This file is part of QuTiP: Quantum Toolbox in Python.
#
#    Copyright (c) 2011 and later, Paul D. Nation and Robert J. Johansson.
#    All rights reserved.
#
#    Redistribution and use in source and binary forms, with or without 
#    modification, are permitted provided that the following conditions are 
#    met:
#
#    1. Redistributions of source code must retain the above copyright notice, 
#       this list of conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#
#    3. Neither the name of the QuTiP: Quantum Toolbox in Python nor the names
#       of its contributors may be used to endorse or promote products derived
#       from this software without specific prior written permission.
#
#    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 
#    "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#    LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A 
#    PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT 
#    HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, 
#    SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT 
#    LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, 
#    DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY 
#    THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT 
#    (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE 
#    OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
###############################################################################
import numpy as np
import scipy.sparse as sp
from qutip.qobj import *
from qutip.qip.gates import *
from qutip.qip.circuit import QubitCircuit
from qutip.qip.models.circuitprocessor import CircuitProcessor


class SpinChain(CircuitProcessor):
    """
    Representation of the physical implementation of a quantum program/algorithm
    on a spin chain qubit system.
    """
    
    def __init__(self, N, correct_global_phase=True):

        super(SpinChain, self).__init__(N, correct_global_phase)
        
        self.sx_ops = [tensor([sigmax() if m == n else identity(2)
                               for n in range(N)])
                       for m in range(N)]
        self.sz_ops = [tensor([sigmaz() if m == n else identity(2)
                               for n in range(N)])
                       for m in range(N)]

        self.sxsy_ops = []
        for n in range(N-1):
            x = [identity(2)] * N
            x[n] = x[n+1] = sigmax()
            y = [identity(2)] * N
            y[n] = y[n+1] = sigmay()
            self.sxsy_ops.append(tensor(x) + tensor(y))
        
        
        self.sx_coeff = [0.25 * 2 * pi] * N
        self.sz_coeff = [1.0 * 2 * pi] * N
        self.sxsy_coeff = [0.1 * 2 * pi] * (N - 1)

        
    def get_ops_and_u(self):
        return (self.sx_ops + self.sz_ops + self.sxsy_ops,
                hstack((self.sx_u, self.sz_u, self.sxsy_u)))

    
    def get_ops_labels(self):
        return ([r"$\sigma_x^%d$" % n for n in range(self.N)] + 
                [r"$\sigma_z^%d$" % n for n in range(self.N)] + 
                [r"$\sigma_x^%d\sigma_x^{%d} + \sigma_y^%d\sigma_y^{%d}$"
                 % (n, n, n, n) for n in range(self.N-1)])


    def load_circuit(self, qc):
        
        gates = self.optimize_circuit(qc).gates
        
        self.global_phase = 0
        self.sx_u = np.zeros((len(gates), len(self.sx_ops)))
        self.sz_u = np.zeros((len(gates), len(self.sz_ops)))
        self.sxsy_u = np.zeros((len(gates), len(self.sxsy_ops)))
        self.T_list = []
        
        n = 0
        for gate in gates:
            
            if gate.name == "ISWAP":
                g = self.sxsy_coeff[min(gate.targets)]
                self.sxsy_u[n, min(gate.targets)] = -g
                T = pi / (4 * g)
                self.T_list.append(T)
                n += 1

            elif gate.name == "SQRTISWAP":
                g = self.sxsy_coeff[min(gate.targets)]
                self.sxsy_u[n, min(gate.targets)] = -g
                T = pi / (8 * g)
                self.T_list.append(T)
                n += 1

            elif gate.name == "RZ":
                g = self.sz_coeff[gate.targets[0]]
                self.sz_u[n, gate.targets[0]] = np.sign(gate.arg_value) * g
                T = abs(gate.arg_value) / (2 * g)
                self.T_list.append(T)
                n += 1
                
            elif gate.name == "RX":
                g = self.sx_coeff[gate.targets[0]]
                self.sx_u[n, gate.targets[0]] = np.sign(gate.arg_value) * g
                T = abs(gate.arg_value) / (2 * g)
                self.T_list.append(T)
                n += 1
                
            elif gate.name == "GLOBALPHASE":
                self.global_phase += gate.arg_value
                
            else:
                raise ValueError("Unsupported gate %s" % gate.name)


def adjacent_gates(qc, setup="linear"):
        """
        Method to resolve 2 qubit gates with non-adjacent control/s or target/s 
        in terms of gates with adjacent interactions for linear/circular spin 
        chain system.
        
        Parameters
        ----------
        qc: Qobj
            The circular spin chain circuit to be resolved
        
        setup: Boolean
            Linear of Circular spin chain setup
            
        Returns
        ----------
        qc_temp: Qobj
            Returns Qobj of resolved gates for the qubit circuit in the desired 
            basis.            
        """  
        qc_temp = QubitCircuit(qc.N, qc.reverse_states)
        swap_gates = ["SWAP", "ISWAP", "SQRTISWAP", "SQRTSWAP", "BERKELEY", 
                      "SWAPalpha"]

        for gate in qc.gates:       
            if gate.name == "CNOT" or gate.name == "CSIGN":                
                start = min([gate.targets[0], gate.controls[0]])
                end = max([gate.targets[0], gate.controls[0]])
                
                if (setup == "linear" or 
                    (setup == "circular" and (end - start) <= N//2)):                  
                    i = start
                    while i < end:
                        if start+end-i-i == 1 and (end-start+1)%2 == 0:
                            #Apply required gate if control and target are 
                            #adjacent to each other, provided |control-target| 
                            #is even.
                            if end == gate.controls[0]:
                                qc_temp.gates.append(Gate(gate.name, 
                                                          targets=[i], 
                                                          controls=[i+1]))
                            else:
                                qc_temp.gates.append(Gate(gate.name, 
                                                          targets=[i+1], 
                                                          controls=[i]))
                                
                        elif start+end-i-i == 2 and (end-start+1)%2 == 1:
                            #Apply a swap between i and its adjacent gate, then 
                            #the required gate if and then another swap if 
                            #control and target have one qubit between them, 
                            #provided |control-target| is odd.
                            qc_temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            if end == gate.controls[0]:
                                qc_temp.gates.append(Gate(gate.name, 
                                                          targets=[i+1], 
                                                          controls=[i+2]))
                            else:
                                qc_temp.gates.append(Gate(gate.name, 
                                                          targets=[i+2], 
                                                          controls=[i+1]))
                            qc_temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            i += 1
                            
                        else:
                            #Swap the target/s and/or control with their 
                            #adjacent qubit to bring them closer.
                            qc_temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            qc_temp.gates.append(Gate("SWAP", 
                                                      targets=[start+end-i-1, 
                                                               start+end-i]))
                        i += 1
                                                
                else:
                    temp = QubitCircuit(N-end+start)
                    i = 0
                    while i < (N-end+start):
                                        
                        if N+start-end-i-i == 1 and (N-end+start)%2 == 0:
                            if end == gate.controls[0]:
                                temp.gates.append(Gate(gate.name, targets=[i], 
                                                       controls=[i+1]))
                            else:
                                temp.gates.append(Gate(gate.name, targets=[i+1], 
                                                       controls=[i]))
                                
                        elif N+start-end-i-i == 2 and (N-end+start)%2 == 1:
                            temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            if end == gate.controls[0]:
                                temp.gates.append(Gate(gate.name, targets=[i+1], 
                                                       controls=[i+2]))
                            else:
                                temp.gates.append(Gate(gate.name, targets=[i+2], 
                                                       controls=[i+1]))
                            temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            i += 1
                            
                        else:
                            temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            temp.gates.append(Gate("SWAP", 
                                                   targets=[N+start-end-i-1, 
                                                            N+start-end-i]))
                        i += 1
                        
                    j = 0
                    for gate in temp.gates:
                        if(j<N-end+2):
                            if gate.name in ["CNOT", "CSIGN"]:
                                qc_temp.append(Gate(gate.name, 
                                                    end+gate.targets[0], 
                                                    end+gate.targets[1]))
                            else:
                                qc_temp.append(Gate(gate.name, 
                                                    [end+gate.targets[0], 
                                                     end+gate.targets[1]]))
                        elif(j==N-end+2):
                            if gate.name in ["CNOT", "CSIGN"]:
                                qc_temp.append(Gate(gate.name, 
                                                    end+gate.targets[0], 
                                                    (end+gate.targets[1])%N))
                            else:
                            qc_temp.append(Gate(gate.name, 
                                                [end+gate.targets[0], 
                                                 (end+gate.targets[1])%N]))
                        else:
                            if gate.name in ["CNOT", "CSIGN"]:
                                qc_temp.append(Gate(gate.name, 
                                                    (end+gate.targets[0])%N, 
                                                    (end+gate.targets[1])%N))
                            else:
                            qc_temp.append(Gate(gate.name, 
                                           [(end+gate.targets[0]%N), 
                                            (end+gate.targets[1])%N]))
                        j = j + 1
                                            
            elif gate.name in swap_gates:
                start = min([gate.targets[0], gate.targets[1]])
                end = max([gate.targets[0], gate.targets[1]])                

                if (setup == "linear" or 
                    (setup == "circular" and (end - start) <= N//2)):            
                    i = start
                    while i < end:
                        if start+end-i-i == 1 and (end-start+1)%2 == 0:
                            qc_temp.gates.append(Gate(gate.name, 
                                                      targets=[i, i+1]))
                        elif (start+end-i-i) == 2 and (end-start+1)%2 == 1:
                            qc_temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            qc_temp.gates.append(Gate(gate.name, 
                                                      targets=[i+1, i+2]))
                            qc_temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                        else:    
                            qc_temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            qc_temp.gates.append(Gate("SWAP", 
                                                      targets=[start+end-i-1, 
                                                               start+end-i]))        
                        i += 1

                else:
                    temp = QubitCircuit(N-end+start)
                    i = 0
                    while i < (N-end+start):
                                        
                        if N+start-end-i-i == 1 and (N-end+start)%2 == 0:
                            if end == gate.controls[0]:
                                temp.gates.append(Gate(gate.name, targets=[i], 
                                                       controls=[i+1]))
                            else:
                                temp.gates.append(Gate(gate.name, targets=[i+1], 
                                                       controls=[i]))
                                
                        elif N+start-end-i-i == 2 and (N-end+start)%2 == 1:
                            temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            if end == gate.controls[0]:
                                temp.gates.append(Gate(gate.name, targets=[i+1], 
                                                       controls=[i+2]))
                            else:
                                temp.gates.append(Gate(gate.name, targets=[i+2], 
                                                       controls=[i+1]))
                            temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            i += 1
                            
                        else:
                            temp.gates.append(Gate("SWAP", targets=[i, i+1]))
                            temp.gates.append(Gate("SWAP", 
                                                   targets=[N+start-end-i-1, 
                                                            N+start-end-i]))
                        i += 1
                        
                    j = 0
                    for gate in temp.gates:
                        if(j<N-end+2):
                            qc_temp.append(Gate(gate.name, [end+gate.targets[0], 
                                                end+gate.targets[1]]))
                        elif(j==N-end+2):
                            qc_temp.append(Gate(gate.name, 
                                                [end+gate.targets[0], 
                                                 (end+gate.targets[1])%N]))
                        else:
                            qc_temp.append(Gate(gate.name, 
                                                [(end+gate.targets[0]%N), 
                                                 (end+gate.targets[1])%N]))
                        j = j + 1                
            
            else:
                qc_temp.gates.append(gate)
        
        return qc_temp


class LinearSpinChain(SpinChain):
    """
    Representation of the physical implementation of a quantum program/algorithm
    on a spin chain qubit system arranged in a linear formation. It is a 
    sub-class of SpinChain.
    """
    
    def __init__(self, N, correct_global_phase=True):

        super(LinearSpinChain, self).__init__(N, correct_global_phase)


    def optimize_circuit(self, qc):    
        self.qc0 = qc
        qc_temp = SpinChain.adjacent_gates(qc, "linear")
        self.qc1 = qc_temp
        qc = qc_temp.resolve_gates(basis=["ISWAP", "RX", "RZ"])
        self.qc2 = qc
        return qc    


class CircularSpinChain(SpinChain):
    """
    Representation of the physical implementation of a quantum program/algorithm
    on a spin chain qubit system arranged in a circular formation. It is a 
    sub-class of SpinChain.
    """
    
    def __init__(self, N, correct_global_phase=True):

        super(CircularSpinChain, self).__init__(N, correct_global_phase)


    def optimize_circuit(self, qc):    
        self.qc0 = qc
        qc_temp = SpinChain.adjacent_gates(qc, "circular")
        self.qc1 = qc_temp
        qc = qc_temp.resolve_gates(basis=["ISWAP", "RX", "RZ"])
        self.qc2 = qc
        return qc        
